"""
택시 사업 자동화 — Streamlit 멀티탭 UI
스펙: exe 배포 / Gemini AI / OCR / 미리보기·백업 / 매핑
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from modules import analyzer, dispatch_log, doc_manager, excel_agent, master_data
from modules.ai_client import (
    API_KEY_URL,
    DEFAULT_MODEL,
    MODEL_CHOICES,
    chat_llm,
    clear_api_key,
    ensure_guide_file,
    has_api_key,
    load_api_key,
    save_api_key,
    setup_guide_markdown,
    test_connection,
)
from modules.mapping import ROLE_LABELS, load_mapping, missing_roles, save_mapping
from modules.ocr_utils import ocr_available
from modules.paths import DATA_ROOT, ensure_storage

st.set_page_config(page_title="택시 사업 자동화", page_icon="🚕", layout="wide")

try:
    ensure_storage()
except Exception as e:
    st.error(f"저장 폴더 초기화 오류: {e}")


def init_state() -> None:
    defaults = {
        "ai_plan": None,
        "ai_preview_df": None,
        "ai_message": "",
        "last_analysis": None,
        "goto_mapping": False,
        "sheet_name": 0,
        "chat_messages": [],
        "master_pending_ops": None,
        "master_pending_reply": "",
        "dispatch_pending_ops": None,
        "dispatch_pending_reply": "",
        "dispatch_pending_year": None,
        "dispatch_pending_month": None,
        "dispatch_edit_path": None,
        "dispatch_dirty": False,
        "dispatch_view_ym": None,
        "doc_draft_active": False,
        "doc_draft_reply": "",
        "doc_draft_seed": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def _clear_doc_draft() -> None:
    """초안 닫기. 위젯 키 삭제는 다음 런 시작 시(위젯 생성 전)에 한다."""
    st.session_state["doc_draft_active"] = False
    st.session_state["doc_draft_reply"] = ""
    st.session_state["doc_draft_seed"] = False
    st.session_state["doc_draft_pending_clear"] = True


def _flush_doc_draft_pending() -> None:
    """위젯 생성 전에 호출: 삭제·seed 반영."""
    if st.session_state.pop("doc_draft_pending_clear", False):
        for k in (
            "doc_draft_title",
            "doc_draft_body",
            "doc_draft_seed_title",
            "doc_draft_seed_body",
        ):
            st.session_state.pop(k, None)
    _apply_doc_draft_seed_if_any()


def _apply_doc_draft_seed_if_any() -> None:
    """text_input/text_area 생성 전에 seed → 위젯 키로 복사."""
    if not st.session_state.pop("doc_draft_seed", False):
        return
    st.session_state["doc_draft_title"] = st.session_state.pop(
        "doc_draft_seed_title", "AI작성_공문"
    )
    st.session_state["doc_draft_body"] = st.session_state.pop("doc_draft_seed_body", "")


def _seed_doc_draft(title: str, body: str, reply: str = "") -> None:
    """AI 초안을 seed에 넣고, 다음 렌더에서 위젯에 반영."""
    st.session_state["doc_draft_active"] = True
    st.session_state["doc_draft_reply"] = reply or ""
    st.session_state["doc_draft_seed"] = True
    st.session_state["doc_draft_seed_title"] = title or "AI작성_공문"
    st.session_state["doc_draft_seed_body"] = body or ""
    # 위젯이 이미 그려진 런에서는 위젯 키를 건드리지 않음 → rerun 후 flush에서 반영


def _render_doc_draft_editor() -> None:
    _flush_doc_draft_pending()
    if not st.session_state.get("doc_draft_active"):
        return

    st.markdown("### 공문 초안 (직접 수정 후 저장)")
    st.info(
        st.session_state.get("doc_draft_reply")
        or "제목·본문을 수정한 뒤 「공문으로 저장」을 누르세요."
    )
    st.text_input("제목", key="doc_draft_title")
    st.text_area("본문", key="doc_draft_body", height=320)
    a1, a2, _ = st.columns([1, 1, 3])
    with a1:
        if st.button("공문으로 저장", type="primary", key="doc_draft_save"):
            title = (st.session_state.get("doc_draft_title") or "").strip()
            body = (st.session_state.get("doc_draft_body") or "").strip()
            try:
                rec = doc_manager.save_text_document(title, body, source="ai_chat")
                msg = (
                    f"공문을 저장했습니다.\n"
                    f"- [{rec.get('category')}] {rec.get('saved_name')}\n"
                    f"- 「공문 모아보기」 목록에서 확인할 수 있습니다."
                )
                st.session_state["chat_messages"].append(
                    {"role": "assistant", "content": msg}
                )
                _clear_doc_draft()
                st.success(msg)
                st.rerun()
            except Exception as e:
                st.error(f"저장 실패: {e}")
    with a2:
        if st.button("초안 취소", key="doc_draft_cancel"):
            st.session_state["chat_messages"].append(
                {"role": "assistant", "content": "공문 초안을 취소했습니다."}
            )
            _clear_doc_draft()
            st.rerun()


def _render_master_lists() -> None:
    master_data.migrate_master_schema()
    vehicles = master_data.load_vehicles()
    drivers = master_data.load_drivers()
    with st.expander("등록된 차량·기사 목록", expanded=False):
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**차량** (상태 메모)")
            if vehicles:
                st.dataframe(
                    [
                        {
                            "차량번호": v.get("plate", ""),
                            "차종": v.get("vehicle_type", ""),
                            "상태메모": v.get("note", ""),
                        }
                        for v in vehicles
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.caption("등록된 차량 없음")
        with c2:
            st.markdown("**기사** (배정·변동·특이)")
            if drivers:
                st.dataframe(
                    [
                        {
                            "이름": d.get("name", ""),
                            "전화": d.get("phone", ""),
                            "배정차량": d.get("assigned_plate", ""),
                            "변동사항": d.get("changes", ""),
                            "특이사항": d.get("note", ""),
                        }
                        for d in drivers
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.caption("등록된 기사 없음")


def _scroll_chat_to_bottom() -> None:
    """고정 높이 채팅 컨테이너를 맨 아래(최신)로 스크롤."""
    import streamlit.components.v1 as components

    components.html(
        """
        <script>
        (function () {
          const doc = window.parent.document;
          const end = doc.getElementById("hana-chat-end");
          if (!end) return;
          let el = end.parentElement;
          while (el && el !== doc.body) {
            const oy = window.parent.getComputedStyle(el).overflowY;
            if (
              el.scrollHeight > el.clientHeight + 40 &&
              (oy === "auto" || oy === "scroll" || el.getAttribute("data-testid") === "stVerticalBlockBorderWrapper")
            ) {
              el.scrollTop = el.scrollHeight;
              break;
            }
            el = el.parentElement;
          }
          try { end.scrollIntoView({ block: "end", behavior: "instant" }); } catch (e) {}
        })();
        </script>
        """,
        height=0,
    )


def _render_dispatch_preview() -> None:
    ops = st.session_state.get("dispatch_pending_ops")
    if not ops:
        return
    year = st.session_state.get("dispatch_pending_year") or datetime.now().year
    month = st.session_state.get("dispatch_pending_month") or datetime.now().month
    st.markdown(f"### 배차일지 변경 미리보기 ({year}-{month:02d})")
    st.info(st.session_state.get("dispatch_pending_reply") or "아래 변경을 확인하세요.")
    rows = dispatch_log.describe_dispatch_ops(ops, int(year), int(month))
    st.dataframe(rows, use_container_width=True, hide_index=True)
    a1, a2, _ = st.columns([1, 1, 3])
    with a1:
        if st.button("배차일지 적용", type="primary", key="dispatch_apply"):
            try:
                path, results = dispatch_log.apply_dispatch_ops(
                    ops, int(year), int(month)
                )
                st.session_state["dispatch_pending_ops"] = None
                st.session_state["dispatch_pending_reply"] = ""
                msg = (
                    f"배차일지 반영: `{path.name}`\n- "
                    + "\n- ".join(results)
                    + "\n\n「엑셀 장부 관리」탭에서 열고 수정할 수 있습니다."
                )
                st.session_state["chat_messages"].append(
                    {"role": "assistant", "content": msg}
                )
                st.success(msg)
                st.rerun()
            except Exception as e:
                st.error(f"적용 실패: {e}")
    with a2:
        if st.button("배차 취소", key="dispatch_cancel"):
            st.session_state["dispatch_pending_ops"] = None
            st.session_state["dispatch_pending_reply"] = ""
            st.session_state["chat_messages"].append(
                {"role": "assistant", "content": "배차일지 변경을 취소했습니다."}
            )
            st.rerun()


def _render_master_preview() -> None:
    ops = st.session_state.get("master_pending_ops")
    if not ops:
        return
    st.markdown("### 마스터 변경 미리보기")
    st.info(st.session_state.get("master_pending_reply") or "아래 변경을 확인하세요.")
    rows = master_data.describe_ops(ops)
    st.dataframe(rows, use_container_width=True, hide_index=True)
    a1, a2, _ = st.columns([1, 1, 3])
    with a1:
        if st.button("적용", type="primary", key="master_apply"):
            try:
                results = master_data.apply_ops(ops)
                st.session_state["master_pending_ops"] = None
                st.session_state["master_pending_reply"] = ""
                msg = "적용 완료:\n- " + "\n- ".join(results)
                st.session_state["chat_messages"].append(
                    {"role": "assistant", "content": msg}
                )
                st.success("마스터에 반영했습니다.")
                st.rerun()
            except Exception as e:
                st.error(f"적용 실패: {e}")
    with a2:
        if st.button("취소", key="master_cancel"):
            st.session_state["master_pending_ops"] = None
            st.session_state["master_pending_reply"] = ""
            st.session_state["chat_messages"].append(
                {"role": "assistant", "content": "마스터 변경을 취소했습니다."}
            )
            st.rerun()


def _render_pending_action_block() -> bool:
    """
    해당 채팅(최신 변경)에 붙는 적용 UI.
    마스터 / 배차 / 공문 초안 중 하나라도 있으면 True.
    """
    has_master = bool(st.session_state.get("master_pending_ops"))
    has_dispatch = bool(st.session_state.get("dispatch_pending_ops"))
    has_doc = bool(st.session_state.get("doc_draft_active"))
    if not (has_master or has_dispatch or has_doc):
        return False
    with st.chat_message("assistant"):
        st.markdown("**⬇️ 이 답변에 대한 적용**")
        if has_master:
            _render_master_preview()
        if has_dispatch:
            _render_dispatch_preview()
        if has_doc:
            _render_doc_draft_editor()
    return True


def tab_chat(model: str) -> None:
    """기사·차량 마스터 + 배차일지 + 공문 초안 + 일반 채팅."""
    st.subheader("AI 채팅")
    st.caption(
        "차량·기사 등록, 배차일지 기입, 공문 초안을 지원합니다. "
        "채팅창에서 위로 스크롤하면 이전 대화를 볼 수 있고, "
        "변경 **적용**은 해당 답변 바로 아래에 붙습니다."
    )

    if not has_api_key():
        render_ai_help(compact=False, key_prefix="chat")
        _render_master_lists()
        return

    _render_master_lists()

    c1, c2 = st.columns([1, 5])
    with c1:
        if st.button("대화 초기화", use_container_width=True):
            st.session_state["chat_messages"] = []
            st.session_state["master_pending_ops"] = None
            st.session_state["master_pending_reply"] = ""
            st.session_state["dispatch_pending_ops"] = None
            st.session_state["dispatch_pending_reply"] = ""
            _clear_doc_draft()
            st.rerun()

    # 고정 높이 채팅 컨테이너: 최신이 아래, 올리면 기록
    with st.container(height=520, border=True):
        messages = st.session_state.get("chat_messages", [])
        if not messages and not (
            st.session_state.get("master_pending_ops")
            or st.session_state.get("dispatch_pending_ops")
            or st.session_state.get("doc_draft_active")
        ):
            st.caption("메시지를 입력해 대화를 시작하세요.")
        for msg in messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
        # 적용 버튼을 해당(최신) 변경 답변에 붙여 표시
        _render_pending_action_block()
        st.markdown('<div id="hana-chat-end"></div>', unsafe_allow_html=True)

    _scroll_chat_to_bottom()

    prompt = st.chat_input(
        "예: 9월 배차일지 만들고 9801에 하종진 / 차량 9801 차종 D-M 등록"
    )
    if not prompt:
        return

    # 상태는 컨테이너 안에서만 그리므로, 여기서는 해석 후 저장하고 rerun
    st.session_state["chat_messages"].append({"role": "user", "content": prompt})
    with st.spinner("해석 중..."):
        try:
            interpreted = master_data.interpret_user_message(prompt, model=model)
        except Exception as e:
            interpreted = {
                "mode": "chat",
                "reply": f"오류: {e}",
                "ops": [],
                "doc": None,
                "dispatch_ops": [],
            }

        mode = interpreted.get("mode")
        if mode == "master_ops" and interpreted.get("ops"):
            st.session_state["master_pending_ops"] = interpreted["ops"]
            st.session_state["master_pending_reply"] = interpreted.get("reply", "")
            reply = (
                (interpreted.get("reply") or "마스터 변경 미리보기입니다.")
                + "\n\n이 답변 **바로 아래**에서 적용 또는 취소를 눌러 주세요."
            )
            st.session_state["chat_messages"].append(
                {"role": "assistant", "content": reply}
            )
        elif mode == "dispatch_ops" and interpreted.get("dispatch_ops") is not None:
            st.session_state["dispatch_pending_ops"] = interpreted["dispatch_ops"]
            st.session_state["dispatch_pending_reply"] = interpreted.get("reply", "")
            st.session_state["dispatch_pending_year"] = interpreted.get("year")
            st.session_state["dispatch_pending_month"] = interpreted.get("month")
            reply = (
                (interpreted.get("reply") or "배차일지 변경 미리보기입니다.")
                + "\n\n이 답변 **바로 아래**에서 **배차일지 적용** 또는 취소를 눌러 주세요."
            )
            st.session_state["chat_messages"].append(
                {"role": "assistant", "content": reply}
            )
        elif mode == "doc_draft" and interpreted.get("doc"):
            doc = interpreted["doc"]
            reply = (
                (interpreted.get("reply") or "공문 초안입니다.")
                + "\n\n이 답변 **바로 아래**에서 제목·본문을 수정한 뒤 「공문으로 저장」을 눌러 주세요."
            )
            st.session_state["chat_messages"].append(
                {"role": "assistant", "content": reply}
            )
            _seed_doc_draft(
                doc.get("title") or "AI작성_공문",
                doc.get("body") or "",
                reply=interpreted.get("reply", ""),
            )
        else:
            try:
                ctx = master_data.master_summary_text()
                aug = list(st.session_state["chat_messages"][:-1]) + [
                    {
                        "role": "user",
                        "content": (
                            f"[현재 마스터]\n{ctx}\n\n[사용자]\n{prompt}"
                        ),
                    }
                ]
                reply = chat_llm(aug, model=model)
            except Exception as e:
                reply = interpreted.get("reply") or f"오류: {e}"
            st.session_state["chat_messages"].append(
                {"role": "assistant", "content": reply}
            )
    st.rerun()


def render_ai_help(*, compact: bool = False, key_prefix: str = "ai") -> None:
    """API 키 없을 때 발급 안내."""
    if has_api_key():
        return

    st.warning("Gemini API 키가 없어 요약·AI 수정을 사용할 수 없습니다.")
    if compact:
        with st.expander("🔑 API 키 발급·입력 방법 (클릭해서 보기)", expanded=False):
            st.markdown(setup_guide_markdown())
            st.link_button("API 키 발급 페이지 열기", API_KEY_URL)
    else:
        st.markdown(setup_guide_markdown())
        st.link_button("API 키 발급 페이지 열기", API_KEY_URL)
        if st.button("안내 파일을 문서 폴더에 저장", key=f"{key_prefix}_save"):
            path = ensure_guide_file()
            if path:
                st.success(f"저장됨: {path}")
            else:
                st.error("안내 파일 저장에 실패했습니다.")


def sidebar() -> str:
    st.sidebar.title("택시 사업 자동화")
    st.sidebar.caption(f"데이터: `{DATA_ROOT}`")

    st.sidebar.subheader("Gemini AI")
    existing = load_api_key()
    key_input = st.sidebar.text_input(
        "Gemini API 키",
        value=existing,
        type="password",
        help="Google AI Studio에서 발급한 키",
    )
    c1, c2 = st.sidebar.columns(2)
    with c1:
        if st.button("키 저장", use_container_width=True):
            if key_input.strip():
                save_api_key(key_input.strip())
                st.sidebar.success("키를 저장했습니다.")
                st.rerun()
            else:
                st.sidebar.error("키를 입력하세요.")
    with c2:
        if st.button("키 삭제", use_container_width=True):
            clear_api_key()
            st.sidebar.info("키를 삭제했습니다.")
            st.rerun()

    model = st.sidebar.selectbox(
        "모델",
        options=MODEL_CHOICES,
        index=MODEL_CHOICES.index(DEFAULT_MODEL) if DEFAULT_MODEL in MODEL_CHOICES else 0,
    )

    if has_api_key():
        st.sidebar.success("AI(Gemini): 키 저장됨")
        if st.sidebar.button("연결 테스트"):
            ok, msg = test_connection(model=model)
            if ok:
                st.sidebar.success(msg)
            else:
                st.sidebar.error(msg)
    else:
        st.sidebar.warning("AI(Gemini): 키 없음 — 요약/AI수정만 비활성")
        with st.sidebar.expander("🔑 키 발급 방법", expanded=True):
            st.markdown(setup_guide_markdown())
            st.link_button("발급 페이지 열기", API_KEY_URL)
            if st.button("안내 파일 저장", key="sidebar_gemini_save"):
                path = ensure_guide_file()
                if path:
                    st.sidebar.success(f"저장: {path.name}")

    ocr_ok, ocr_msg = ocr_available()
    if ocr_ok:
        st.sidebar.info("OCR: 사용 가능")
    else:
        st.sidebar.caption(f"OCR: {ocr_msg}")

    st.sidebar.markdown("---")
    st.sidebar.markdown(
        "종료는 **트레이 아이콘**(실행 시) 또는 이 브라우저 탭을 닫은 뒤 런처에서 종료하세요."
    )
    return model


def render_mapping_ui(df_columns: list[str], *, key_prefix: str = "map") -> None:
    st.subheader("컬럼 매핑")
    st.write("장부 열 이름을 앱이 이해하는 역할에 연결합니다.")
    mapping = load_mapping()
    cols = ["(선택 안 함)"] + list(df_columns)
    new_map = {}
    for role, label in ROLE_LABELS.items():
        current = mapping.get(role)
        idx = cols.index(current) if current in cols else 0
        choice = st.selectbox(label, cols, index=idx, key=f"{key_prefix}_{role}")
        new_map[role] = None if choice == "(선택 안 함)" else choice
    if st.button("매핑 저장", type="primary", key=f"{key_prefix}_save"):
        save_mapping(new_map)
        st.success("매핑을 저장했습니다.")
        st.session_state["goto_mapping"] = False


def tab_documents(model: str) -> None:
    st.subheader("공문 모아보기")
    st.write(
        "PDF 업로드 또는 AI 채팅으로 작성한 공문(.txt)을 모읍니다. "
        "스캔 PDF는 OCR을 시도할 수 있습니다."
    )

    up = st.file_uploader("PDF 업로드", type=["pdf"], key="pdf_up")
    if up is not None and st.button("저장", key="pdf_save"):
        try:
            rec = doc_manager.save_uploaded_pdf(up)
            st.success(f"저장: [{rec['category']}] {rec['saved_name']}")
        except Exception as e:
            st.error(f"저장 실패: {e}")

    items = doc_manager.list_pdfs()
    if not items:
        st.info("저장된 공문이 없습니다.")
        return

    labels = []
    for i in items:
        src = i.get("source") or ""
        ftype = i.get("file_type") or (
            "txt" if str(i.get("path", "")).lower().endswith(".txt") else "pdf"
        )
        tag = "AI작성" if src == "ai_chat" or ftype == "txt" else "PDF"
        title = i.get("title") or i.get("original_name")
        labels.append(
            f"{i.get('uploaded_at','')} | [{i.get('category','')}] [{tag}] {title}"
        )
    choice = st.selectbox("공문 목록", labels)
    selected = items[labels.index(choice)]

    if not has_api_key():
        render_ai_help(compact=True, key_prefix="doc_gemini")

    is_txt = str(selected.get("path", "")).lower().endswith(".txt") or selected.get(
        "file_type"
    ) == "txt"
    use_ocr = st.checkbox("텍스트 없을 때 OCR 사용", value=not is_txt, disabled=is_txt)
    c1, c2 = st.columns(2)
    with c1:
        if st.button("텍스트 미리보기"):
            try:
                text = doc_manager.extract_text(
                    selected["path"], use_ocr_fallback=use_ocr and not is_txt
                )
                st.text_area("추출 텍스트", text[:8000], height=300)
            except Exception as e:
                st.error(str(e))
    with c2:
        if st.button("AI 요약"):
            if not has_api_key():
                st.error("API 키가 없어 요약할 수 없습니다. 아래 안내를 따라 주세요.")
                render_ai_help(compact=False, key_prefix="doc_sum")
            else:
                with st.spinner("요약 중..."):
                    try:
                        summary = doc_manager.summarize_pdf(selected["path"], model=model)
                        st.markdown("### 요약")
                        st.write(summary)
                    except Exception as e:
                        st.error(str(e))

    if selected.get("summary"):
        st.markdown("### 저장된 요약")
        st.write(selected["summary"])


def tab_excel() -> None:
    st.subheader("엑셀 장부 관리")

    mode = st.radio(
        "작업 대상",
        ["일반 장부", "배차일지"],
        horizontal=True,
        key="excel_work_mode",
    )

    if mode == "배차일지":
        _tab_excel_dispatch()
        return

    c1, c2 = st.columns(2)
    with c1:
        up = st.file_uploader("엑셀 업로드 (.xlsx)", type=["xlsx"], key="xlsx_up")
        if up is not None and st.button("원본으로 저장", key="xlsx_save"):
            try:
                path = excel_agent.save_uploaded_excel(up)
                st.success(f"저장 및 현재 장부 지정: {path}")
            except Exception as e:
                st.error(str(e))
    with c2:
        if st.button("표준 템플릿 만들기"):
            try:
                path = excel_agent.create_template()
                st.success(f"템플릿 생성·지정: {path}")
            except Exception as e:
                st.error(str(e))

    files = excel_agent.list_excel_files()
    for kind, paths in files.items():
        if paths:
            with st.expander(f"{kind} ({len(paths)})"):
                for p in paths[:30]:
                    cols = st.columns([4, 1])
                    cols[0].write(p.name)
                    if cols[1].button("사용", key=f"use_{kind}_{p.name}"):
                        excel_agent.set_current_master(p)
                        st.rerun()

    master = excel_agent.get_current_master()
    if not master:
        st.warning("현재 장부가 없습니다. 업로드하거나 템플릿을 만드세요.")
        return

    st.info(f"현재 장부: `{master}`")
    try:
        sheets = excel_agent.list_sheet_names(master)
        sheet = st.selectbox("시트 선택", sheets, index=0)
        st.session_state["sheet_name"] = sheet
        df = excel_agent.load_excel(master, sheet_name=sheet)
        st.dataframe(df, use_container_width=True)
        st.caption(f"행 {len(df)} / 열 {len(df.columns)}")

        st.markdown("---")
        render_mapping_ui([str(c) for c in df.columns], key_prefix="excel_map")
    except Exception as e:
        st.error(str(e))


def _tab_excel_dispatch() -> None:
    """배차일지 관리: 이번/다음 달, 수동 수정, 수익 엑셀→휴차, 달 이동 경고."""
    from pathlib import Path

    from modules import dispatch_export, revenue_import, wage_settings
    from modules.business_day import business_date, next_month

    st.write(
        "양식: 순서·차번·차종·성명·1~31·근무일수. "
        "TIMS 수익 엑셀로 **차량별 당월수익·초과지급**을 보고, "
        "엑셀에 나온 날 기준 **운행 없음/수익 0 → 휴차**, 수익 있으면 근무. "
        "가져올 때 **기사 배정차량·변동사항 `[배정]`** 도 함께 최신화합니다. "
        "**배정 기사가 없는 차량은 일자를 기입하지 않습니다.** "
        "시급·초과기준·공제비율은 아래에서 변경할 수 있습니다."
    )

    try:
        # 켤 때(탭 진입 시) 한 번: 없으면 생성, 있으면 유지
        p_cur, p_next, is_new = dispatch_log.ensure_current_and_next_months()
        bd = business_date()
        if is_new:
            st.success(
                f"영업일 {bd} 확인 — 배차일지 준비: `{p_cur.name}`, `{p_next.name}`"
            )
        else:
            st.caption(f"영업일 {bd} · 유지 중: {p_cur.name} / {p_next.name}")
    except Exception as e:
        st.error(f"월 파일 준비 실패: {e}")
        return

    bd = business_date()
    cur_y, cur_m = bd.year, bd.month
    ny, nm = next_month(cur_y, cur_m)
    month_options = [
        (cur_y, cur_m, f"{cur_y}-{cur_m:02d} (이번 달)"),
        (ny, nm, f"{ny}-{nm:02d} (다음 달)"),
    ]
    for p in dispatch_log.list_dispatch_files():
        ym_file = dispatch_log.parse_year_month_from_name(p)
        if not ym_file:
            continue
        if ym_file not in {(cur_y, cur_m), (ny, nm)}:
            month_options.append((ym_file[0], ym_file[1], f"{ym_file[0]}-{ym_file[1]:02d}"))

    seen = set()
    uniq = []
    for y, m, label in month_options:
        if (y, m) in seen:
            continue
        seen.add((y, m))
        uniq.append((y, m, label))

    # None/잘못된 값이면 영업일 기준으로 초기화 (TypeError 방지)
    ym = st.session_state.get("dispatch_view_ym")
    if not isinstance(ym, (tuple, list)) or len(ym) != 2:
        ym = (cur_y, cur_m)
        st.session_state["dispatch_view_ym"] = ym

    labels = [x[2] for x in uniq]
    cur_idx = next(
        (i for i, x in enumerate(uniq) if x[0] == ym[0] and x[1] == ym[1]),
        0,
    )

    pick = st.selectbox("볼 달", labels, index=cur_idx, key="dispatch_month_select")
    sel_y, sel_m = uniq[labels.index(pick)][0], uniq[labels.index(pick)][1]

    # 달 이동 + dirty 경고
    if (sel_y, sel_m) != (ym[0], ym[1]):
        if st.session_state.get("dispatch_dirty"):
            st.warning("저장하지 않은 배차일지 수정이 있습니다. 달을 바꾸면 편집 내용이 사라질 수 있습니다.")
            c_ok, c_no = st.columns(2)
            with c_ok:
                if st.button("저장하지 않고 이동", type="primary", key="dispatch_force_month"):
                    st.session_state["dispatch_view_ym"] = (sel_y, sel_m)
                    st.session_state["dispatch_dirty"] = False
                    st.session_state["dispatch_edit_path"] = str(
                        dispatch_log.ensure_month(sel_y, sel_m)
                    )
                    st.rerun()
            with c_no:
                if st.button("이동 취소", key="dispatch_cancel_month"):
                    st.rerun()
            return
        st.session_state["dispatch_view_ym"] = (sel_y, sel_m)
        st.session_state["dispatch_edit_path"] = str(dispatch_log.ensure_month(sel_y, sel_m))
        st.rerun()

    path = dispatch_log.ensure_month(sel_y, sel_m)
    st.session_state["dispatch_edit_path"] = str(path)
    st.info(f"편집 중: `{path.name}`")

    assign_lines = dispatch_log.list_assignment_changes(sel_y, sel_m)
    with st.expander("이달 배정 변동 (기사 변동사항 `[배정]`)", expanded=bool(assign_lines)):
        st.caption(
            "기사 **변동사항** 형식: `[배정] YYYY-MM-DD 이전차→이후차` "
            "(예: `[배정] 2025-09-10 12가3456→78가9012`). "
            "대차 시 기사 **배정차량**을 새 차로 바꾸고 변동사항에 한 줄을 남기면, "
            "TIMS 가져오기 또는 아래 버튼으로 배차일지에 반영됩니다. "
            "차량 메모는 고장 등 **상태**만 적습니다."
        )
        if assign_lines:
            for line in assign_lines:
                st.write(f"- {line}")
        else:
            st.caption("이달에 해당하는 `[배정]` 변동이 없습니다.")
        if st.button("기사 배정·변동사항 반영", key="dispatch_apply_assign"):
            try:
                msgs = dispatch_log.apply_assignments_to_month(sel_y, sel_m)
                st.session_state["dispatch_dirty"] = False
                if any("열려 있어" in m for m in msgs):
                    st.error("\n".join(m for m in msgs if "열려 있어" in m))
                else:
                    st.success("기사 배정·변동사항을 반영했습니다.")
                    st.text("\n".join(msgs[:40]))
                    st.rerun()
            except Exception as e:
                st.error(f"배정 반영 실패: {e}")

    # —— 시급·초과금 설정 ——
    with st.expander("시급·초과금 설정 (전원 동일)", expanded=False):
        ws = wage_settings.load_settings()
        st.caption(
            "초과금 = (월수입 − 기준액) × 기사지급비율. "
            "비율·기준·시급은 언제든 바꿀 수 있고, TIMS 수익 반영 시 해당 달에 스냅샷이 남습니다."
        )
        c_w1, c_w2, c_w3 = st.columns(3)
        with c_w1:
            hourly = st.number_input(
                "시급 (원)",
                min_value=0.0,
                value=float(ws["hourly_wage"]),
                step=100.0,
                format="%.0f",
                key="wage_hourly",
            )
        with c_w2:
            thr = st.number_input(
                "초과금 기준액 (원)",
                min_value=0.0,
                value=float(ws["excess_threshold"]),
                step=100000.0,
                format="%.0f",
                key="wage_threshold",
            )
        with c_w3:
            share_pct = st.number_input(
                "초과분 기사 지급 (%)",
                min_value=0.0,
                max_value=100.0,
                value=float(ws["driver_share_rate"]) * 100.0,
                step=1.0,
                format="%.1f",
                key="wage_share_pct",
                help="예: 90 → 회사가 10% 공제",
            )
        b_save, b_snap = st.columns(2)
        with b_save:
            if st.button("설정 저장", type="primary", key="wage_save_btn"):
                wage_settings.save_settings(
                    hourly_wage=float(hourly),
                    excess_threshold=float(thr),
                    driver_share_rate=float(share_pct) / 100.0,
                )
                st.success("시급·초과금 설정을 저장했습니다.")
                st.rerun()
        with b_snap:
            if st.button(f"{sel_y}-{sel_m:02d} 달에 현재 요율 적용", key="wage_snap_btn"):
                wage_settings.save_settings(
                    hourly_wage=float(hourly),
                    excess_threshold=float(thr),
                    driver_share_rate=float(share_pct) / 100.0,
                )
                wage_settings.save_month_snapshot(sel_y, sel_m)
                st.success(f"{sel_y}-{sel_m:02d} 요율 스냅샷을 저장했습니다.")
                st.rerun()

    st.caption(wage_settings.rates_caption(sel_y, sel_m))

    # —— TIMS 수익 엑셀 ——
    with st.expander(
        "TIMS 수익 엑셀 가져오기 (배정·변동·수익·휴차 반영)",
        expanded=False,
    ):
        st.caption("반영 시: ① 기사 배정차량 맞춤 ② 변동사항 `[배정]` ③ 수익·휴차")
        up = st.file_uploader("수익 엑셀 (.xlsx)", type=["xlsx"], key="revenue_xlsx")
        if up is not None:
            try:
                rdf = pd.read_excel(up, engine="openpyxl")
                st.dataframe(rdf.head(20), use_container_width=True)
                suggested = revenue_import.suggest_columns(rdf)
                cols = ["(선택 안 함)"] + [str(c) for c in rdf.columns]
                d_col = st.selectbox(
                    "날짜/일시 열",
                    cols,
                    index=cols.index(suggested["date"]) if suggested.get("date") in cols else 0,
                    key="rev_date_col",
                )
                p_col = st.selectbox(
                    "차번 열",
                    cols,
                    index=cols.index(suggested["plate"]) if suggested.get("plate") in cols else 0,
                    key="rev_plate_col",
                )
                r_col = st.selectbox(
                    "수익금 열",
                    cols,
                    index=cols.index(suggested["revenue"])
                    if suggested.get("revenue") in cols
                    else 0,
                    key="rev_rev_col",
                )
                if st.button(
                    "수익 반영 (무운행·0원→휴차, 수익→근무)",
                    type="primary",
                    key="rev_apply",
                ):
                    if "(선택" in d_col or "(선택" in p_col or "(선택" in r_col:
                        st.error("날짜·차번·수익 열을 모두 선택하세요.")
                    else:
                        revenue_import.save_revenue_mapping(
                            {"date": d_col, "plate": p_col, "revenue": r_col}
                        )
                        agg = revenue_import.aggregate_revenue(
                            rdf, date_col=d_col, plate_col=p_col, revenue_col=r_col
                        )
                        st.dataframe(agg.head(50), use_container_width=True)
                        msgs = dispatch_log.apply_revenue_to_dispatch(agg)
                        plate_info = wage_settings.save_revenues_from_agg(agg, snapshot_wage=True)
                        if plate_info:
                            msgs.append(
                                "차량별 당월수익 저장: "
                                + ", ".join(
                                    f"{k} 총 {v['total']:,.0f}원 ({v['plates']}대)"
                                    for k, v in plate_info.items()
                                )
                            )
                        st.session_state["dispatch_dirty"] = False
                        if any("열려 있어" in m for m in msgs):
                            st.error("\n".join(m for m in msgs if "열려 있어" in m))
                        else:
                            st.success("반영 완료")
                        st.text("\n".join(msgs[:40]))
                        if not any("열려 있어" in m for m in msgs):
                            st.rerun()
            except Exception as e:
                st.error(f"수익 엑셀 처리 실패: {e}")

    try:
        df = dispatch_log.load_path(path)
        vehicles = master_data.load_vehicles()
        drivers = master_data.load_drivers()

        plate_options = [""] + [
            str(v.get("plate")) for v in vehicles if str(v.get("plate") or "").strip()
        ]
        name_options = [""] + sorted(
            {
                str(d.get("name")).strip()
                for d in drivers
                if str(d.get("name") or "").strip()
            }
        )
        # 표에 이미 있는 값도 선택지에 포함
        for col, opts in (("차번", plate_options), ("성명", name_options)):
            for val in df[col].astype(str).tolist():
                v = val.strip()
                if v and v not in opts and v.lower() != "nan":
                    opts.append(v)

        vtype_by_plate = {
            str(v.get("plate")).strip(): str(v.get("vehicle_type") or "")
            for v in vehicles
            if str(v.get("plate") or "").strip()
        }
        driver_by_plate = {
            str(d.get("assigned_plate")).strip(): str(d.get("name") or "").strip()
            for d in drivers
            if str(d.get("assigned_plate") or "").strip()
                and str(d.get("name") or "").strip()
        }
        # 정규화 키도 넣어 enrichment가 공백 차이에도 동작
        for k, name in list(master_data.plate_to_driver_name().items()):
            if k and name and k not in driver_by_plate:
                driver_by_plate[k] = name

        st.caption(
            "차번·성명은 **AI 채팅에 등록된 차량·기사** 목록에서 선택하세요. "
            "**당월수익·초과지급**은 TIMS 엑셀 반영값(읽기 전용)입니다."
        )

        with st.expander("등록 차량으로 행 추가", expanded=False):
            if not plate_options[1:]:
                st.warning("등록된 차량이 없습니다. AI 채팅에서 차량을 먼저 등록하세요.")
            else:
                add_plate = st.selectbox(
                    "추가할 차량",
                    plate_options[1:],
                    key="dispatch_add_plate",
                )
                if st.button("선택한 차량 행 추가", key="dispatch_add_row_btn"):
                    cur = df.copy()
                    target = add_plate.replace(" ", "").upper()
                    exists = any(
                        str(r.get("차번", "")).replace(" ", "").upper() == target
                        for _, r in cur.iterrows()
                    )
                    if exists:
                        st.warning(f"이미 있는 차번입니다: {add_plate}")
                    else:
                        from modules.dispatch_log import _empty_row

                        order = int(cur["순서"].max()) + 1 if len(cur) else 1
                        cur = pd.concat(
                            [
                                cur,
                                pd.DataFrame(
                                    [
                                        _empty_row(
                                            order,
                                            plate=add_plate,
                                            vtype=vtype_by_plate.get(add_plate, ""),
                                            name=driver_by_plate.get(add_plate, ""),
                                        )
                                    ]
                                ),
                            ],
                            ignore_index=True,
                        )
                        dispatch_log.save_path(cur, path, backup=True)
                        st.session_state["dispatch_dirty"] = False
                        st.success(f"행 추가·저장: {add_plate}")
                        st.rerun()

        if not plate_options[1:] and not name_options[1:]:
            st.info("등록된 차량·기사가 없습니다. AI 채팅 탭에서 먼저 등록하세요.")

        view_df = wage_settings.attach_revenue_columns(df, sel_y, sel_m)
        # 열 순서: 고정열 → 수익 → 일자 → 근무일수
        day_cols = [str(i) for i in range(1, 32)]
        ordered = (
            ["순서", "차번", "차종", "성명", "당월수익", "초과지급"]
            + day_cols
            + ["근무일수"]
        )
        view_df = view_df[[c for c in ordered if c in view_df.columns]]

        edited = st.data_editor(
            view_df,
            use_container_width=True,
            num_rows="dynamic",
            key=f"dispatch_editor_{path.name}",
            column_config={
                "순서": st.column_config.NumberColumn("순서", disabled=True),
                "차번": st.column_config.SelectboxColumn(
                    "차번",
                    options=plate_options,
                    required=False,
                    help="등록된 차량에서 선택",
                ),
                "차종": st.column_config.TextColumn("차종"),
                "성명": st.column_config.SelectboxColumn(
                    "성명",
                    options=name_options,
                    required=False,
                    help="등록된 기사에서 선택",
                ),
                "당월수익": st.column_config.NumberColumn(
                    "당월수익",
                    disabled=True,
                    format="%.0f",
                    help="TIMS 엑셀 차량별 합계",
                ),
                "초과지급": st.column_config.NumberColumn(
                    "초과지급",
                    disabled=True,
                    format="%.0f",
                    help="(당월수익−기준)×지급비율",
                ),
                "근무일수": st.column_config.NumberColumn("근무일수", disabled=True),
            },
            disabled=["순서", "근무일수", "당월수익", "초과지급"],
        )
        # dirty: 관리 열만 비교
        base_cols = [c for c in df.columns if c in edited.columns]
        if not edited[base_cols].equals(df[base_cols]):
            st.session_state["dispatch_dirty"] = True

        plate_rev = wage_settings.get_plate_revenues(sel_y, sel_m)
        if plate_rev:
            rates = wage_settings.get_month_rates(sel_y, sel_m)
            over_n = sum(
                1
                for v in plate_rev.values()
                if v > float(rates.get("excess_threshold") or 0)
            )
            st.caption(
                f"TIMS 반영 차량 {len(plate_rev)}대 · "
                f"월합 {sum(plate_rev.values()):,.0f}원 · "
                f"초과 해당 {over_n}대"
            )
        else:
            st.caption("아직 이달 TIMS 수익이 없습니다. 위에서 엑셀을 가져오세요.")

        def _enrich_from_master(frame: pd.DataFrame) -> pd.DataFrame:
            from modules.plate_utils import norm_plate as _np

            out = frame.copy()
            for i, row in out.iterrows():
                plate = str(row.get("차번") or "").strip()
                if not plate:
                    continue
                if not str(row.get("차종") or "").strip() and plate in vtype_by_plate:
                    out.at[i, "차종"] = vtype_by_plate[plate]
                if not str(row.get("성명") or "").strip():
                    name = driver_by_plate.get(plate) or driver_by_plate.get(_np(plate), "")
                    if name:
                        out.at[i, "성명"] = name
            return out

        def _strip_display_cols(frame: pd.DataFrame) -> pd.DataFrame:
            drop = [c for c in ("당월수익", "초과지급") if c in frame.columns]
            return frame.drop(columns=drop, errors="ignore")

        b1, b2, b3 = st.columns(3)
        with b1:
            if st.button("배차일지 저장", type="primary", key="dispatch_save_btn"):
                try:
                    to_save = _enrich_from_master(_strip_display_cols(edited))
                    saved = dispatch_log.save_path(to_save, path, backup=True)
                    st.session_state["dispatch_dirty"] = False
                    st.session_state.pop("dispatch_locked_path", None)
                    st.success(f"저장됨: {saved.name}")
                    st.rerun()
                except dispatch_log.FileLockedError as e:
                    st.session_state["dispatch_locked_path"] = str(path)
                    st.session_state["dispatch_locked_df"] = _strip_display_cols(edited)
                    st.error(str(e))
                except Exception as e:
                    st.error(f"저장 실패: {e}")
            if st.session_state.get("dispatch_locked_path") == str(path):
                if st.button("다시 저장", type="primary", key="dispatch_retry_save"):
                    try:
                        pending = st.session_state.get("dispatch_locked_df")
                        if pending is None:
                            pending = _strip_display_cols(edited)
                        to_save = _enrich_from_master(pending)
                        saved = dispatch_log.save_path(to_save, path, backup=True)
                        st.session_state["dispatch_dirty"] = False
                        st.session_state.pop("dispatch_locked_path", None)
                        st.session_state.pop("dispatch_locked_df", None)
                        st.success(f"저장됨: {saved.name}")
                        st.rerun()
                    except dispatch_log.FileLockedError as e:
                        st.error(str(e))
                    except Exception as e:
                        st.error(f"저장 실패: {e}")
        with b2:
            if st.button("기사 배정·변동사항으로 맞추기", key="dispatch_resync"):
                try:
                    msgs = dispatch_log.apply_assignments_to_month(sel_y, sel_m)
                    st.session_state["dispatch_dirty"] = False
                    if any("열려 있어" in m for m in msgs):
                        st.error("\n".join(m for m in msgs if "열려 있어" in m))
                    else:
                        st.success("기사 배정차량·변동사항 기준으로 맞추고 저장했습니다.")
                        st.text("\n".join(msgs[:40]))
                        st.rerun()
                except Exception as e:
                    st.error(str(e))
        with b3:
            if st.button("현재 장부로도 지정", key="dispatch_as_master"):
                excel_agent.set_current_master(path)
                st.success("현재 장부 포인터를 이 배차일지로 지정했습니다.")

        st.markdown("---")
        st.subheader("제출용 내보내기 (요약·결제란)")

        preview = dispatch_export.compute_summary(
            _strip_display_cols(edited), sel_y, sel_m
        )
        saved_rev = dispatch_export.get_revenue_total(sel_y, sel_m)
        rev_input = st.number_input(
            f"{sel_m}월 운송수입금총액",
            min_value=0.0,
            value=float(saved_rev or preview["revenue_total"] or 0),
            step=1000.0,
            format="%.0f",
            key=f"dispatch_rev_total_{sel_y}_{sel_m}",
            help="TIMS 수익 반영 시 자동 저장됩니다. 필요하면 수동으로 수정하세요.",
        )
        st.caption(preview["line1"])
        st.caption(
            dispatch_export.compute_summary(
                _strip_display_cols(edited),
                sel_y,
                sel_m,
                revenue_total=float(rev_input),
            )["line2"]
        )
        try_hwp = st.checkbox(
            "한글이 있으면 HWP도 생성",
            value=True,
            key="dispatch_try_hwp",
        )
        if st.button("제출용 파일 만들기 (xlsx + HWP)", type="primary", key="dispatch_export_btn"):
            try:
                to_save = _enrich_from_master(_strip_display_cols(edited))
                dispatch_log.save_path(to_save, path, backup=True)
                st.session_state["dispatch_dirty"] = False
                result = dispatch_export.export_submission(
                    sel_y,
                    sel_m,
                    revenue_total=float(rev_input),
                    df=to_save,
                    try_hwp=try_hwp,
                )
                st.success(f"제출용 xlsx: `{result['xlsx']}`")
                if result.get("hwp"):
                    st.success(f"제출용 HWP: `{result['hwp']}`")
                elif result.get("hwp_error"):
                    st.warning(result["hwp_error"])
                st.info(
                    f"{result['summary']['line1']}\n{result['summary']['line2']}"
                )
            except Exception as e:
                st.error(f"내보내기 실패: {e}")
    except Exception as e:
        st.error(str(e))


def tab_ai_edit(model: str) -> None:
    st.subheader("AI 자동 수정·작성")
    st.write("계획을 먼저 보여 준 뒤, **적용**을 눌러야 저장됩니다. 적용 시 백업이 남습니다.")

    if not has_api_key():
        render_ai_help(compact=False, key_prefix="ai_tab")
        if st.button("마지막 백업으로 되돌리기", key="undo_ai_off"):
            try:
                path = excel_agent.undo_last_backup()
                st.success(f"복구됨: {path.name}")
            except Exception as e:
                st.error(str(e))
        return

    master = excel_agent.get_current_master()
    if not master:
        st.warning("먼저 엑셀 장부를 지정하세요.")
        return

    try:
        sheet = st.session_state.get("sheet_name") or 0
        df = excel_agent.load_excel(master, sheet_name=sheet)
    except Exception as e:
        st.error(str(e))
        return

    cmd = st.text_area(
        "자연어 명령",
        placeholder="예: 최신 PDF 공문의 유가보조금 단가를 장부에 반영해줘",
        height=100,
    )
    use_pdf = st.checkbox("최신 PDF 공문 참고", value=True)

    if st.button("계획 미리보기", type="primary") and cmd.strip():
        with st.spinner("AI가 수정 계획을 만드는 중..."):
            try:
                plan = excel_agent.plan_edit_from_nl(
                    cmd.strip(), df, model=model, use_pdf_context=use_pdf
                )
                new_df, message = excel_agent.apply_plan(df, plan)
                st.session_state["ai_plan"] = plan
                st.session_state["ai_preview_df"] = new_df
                st.session_state["ai_message"] = message
            except Exception as e:
                st.error(f"계획 생성 실패: {e}")
                st.session_state["ai_plan"] = None

    if st.session_state.get("ai_plan") is not None:
        st.markdown("### 계획 (JSON)")
        st.json(st.session_state["ai_plan"])
        st.write(st.session_state.get("ai_message", ""))
        st.markdown("### 미리보기 (변경 후)")
        st.dataframe(st.session_state["ai_preview_df"].tail(40), use_container_width=True)

        a1, a2, a3 = st.columns(3)
        with a1:
            if st.button("적용 (새 파일로 저장)", type="primary"):
                try:
                    path = excel_agent.save_as_edited(
                        st.session_state["ai_preview_df"], label="AI수정"
                    )
                    st.success(f"저장됨: {path}")
                    st.session_state["ai_plan"] = None
                    st.session_state["ai_preview_df"] = None
                except Exception as e:
                    st.error(str(e))
        with a2:
            if st.button("계획 취소"):
                st.session_state["ai_plan"] = None
                st.session_state["ai_preview_df"] = None
                st.rerun()
        with a3:
            if st.button("백업으로 되돌리기"):
                try:
                    path = excel_agent.undo_last_backup()
                    st.success(f"복구: {path.name}")
                except Exception as e:
                    st.error(str(e))


def tab_analysis() -> None:
    st.subheader("데이터 분석 및 저장")

    if st.session_state.get("goto_mapping"):
        st.warning("컬럼 매핑이 필요합니다. 아래 또는『엑셀 장부 관리』탭에서 설정하세요.")

    master = excel_agent.get_current_master()
    if not master:
        st.warning("마스터 엑셀이 없습니다.")
        return

    try:
        sheet = st.session_state.get("sheet_name") or 0
        df = excel_agent.load_excel(master, sheet_name=sheet)
    except Exception as e:
        st.error(str(e))
        return

    miss = missing_roles(df.columns)
    mapping_shown = False
    if miss:
        st.error(f"필수 열 체크리스트 — 부족: {', '.join(miss)}")
        if st.button("컬럼 매핑으로 이동", key="analysis_goto_mapping"):
            st.session_state["goto_mapping"] = True
        render_mapping_ui([str(c) for c in df.columns], key_prefix="analysis_map")
        mapping_shown = True

    if st.button("분석 실행", key="analysis_run"):
        try:
            result = analyzer.analyze_ledger(df)
            st.session_state["last_analysis"] = result
            if result.get("need_mapping"):
                st.session_state["goto_mapping"] = True
                st.error(result["summary_text"])
                if not mapping_shown:
                    render_mapping_ui(
                        [str(c) for c in df.columns], key_prefix="analysis_map"
                    )
            else:
                st.text(result["summary_text"])
                monthly = result["monthly"]
                if monthly is not None and not monthly.empty:
                    st.line_chart(monthly.set_index("년월")[["매출", "비용", "손익"]])
                    st.dataframe(monthly, use_container_width=True)
        except Exception as e:
            st.error(str(e))

    if st.session_state.get("last_analysis") and st.session_state["last_analysis"].get("ok"):
        if st.button("리포트 저장", key="analysis_save_report"):
            try:
                path = analyzer.save_report(st.session_state["last_analysis"])
                st.success(f"저장됨: {path}")
            except Exception as e:
                st.error(str(e))

    reports = analyzer.list_reports()
    if reports:
        st.markdown("#### 저장된 리포트")
        for p in reports[:20]:
            st.write(f"- {p.parent.name} / {p.name}")


def main() -> None:
    init_state()
    try:
        master_data.migrate_master_schema()
    except Exception:
        pass
    model = sidebar()
    st.title("택시 사업 자동화")
    st.caption("파일은 PC 문서 폴더에 저장 · AI는 Google Gemini (키 필요)")

    # 라디오로 한 탭만 실행 (전체 탭 동시 렌더 방지)
    tab_names = [
        "AI 채팅",
        "공문 모아보기",
        "엑셀 장부 관리",
        "AI 자동 수정·작성",
        "데이터 분석 및 저장",
    ]
    tab = st.radio(
        "메뉴",
        tab_names,
        horizontal=True,
        label_visibility="collapsed",
        key="main_nav_tab",
    )
    st.markdown("---")
    if tab == "AI 채팅":
        tab_chat(model)
    elif tab == "공문 모아보기":
        tab_documents(model)
    elif tab == "엑셀 장부 관리":
        tab_excel()
    elif tab == "AI 자동 수정·작성":
        tab_ai_edit(model)
    else:
        tab_analysis()


if __name__ == "__main__":
    main()
