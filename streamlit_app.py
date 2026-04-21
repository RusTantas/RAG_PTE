import streamlit as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from rag_system import rag_system

st.set_page_config(
    page_title="ПТЭ/ИДП - Поиск нарушений",
    page_icon="🚂",
    layout="wide"
)

st.title("Система поиска нарушений ПТЭ/ИДП")
st.markdown("**Правила технической эксплуатации железных дорог РФ**")

with st.sidebar:
    st.header("О системе")
    st.info("""
    Автоматический поиск нарушений по базе правил ПТЭ и ИДП.
    
    **Алгоритм:**
    1. Keyword search → точный результат
    2. Fuzzy search → уточненный результат
    3. LLM candidates → выбор пункта
    4. Формирование замечания
    """)
    
    st.header("Карта документов")
    st.markdown("""
    **ПТЭ:**
    - Раздел 1: Общие положения
    - Раздел 2: Работники, свидетельства, медосмотры
    - Раздел 3: САУТ и инфраструктура
    - Раздел 5: Пути, стрелочные переводы
    - Раздел 6: Светофоры, видимость
    - Раздел 7: Электросвязь
    - Раздел 8: Электроснабжение
    - Раздел 9: Подвижной состав
    
    **ИДП:**
    - Приложение 6: Разграничение временем
    - Приложение 9: Прием/отправление поездов
    - Приложение 10: Маневровая работа
    - Приложение 11: Опасные грузы
    - Приложение 12: Закрепление башмаками
    - Приложение 13: Хозяйственные поезда
    - Приложение 14: Замыкание стрелок
    - Приложение 16: Спецподвижной состав
    """)

st.markdown("---")

col1, col2 = st.columns([3, 1])

with col1:
    remark = st.text_area(
        "Введите замечание о нарушении:",
        value=st.session_state.get("remark_input", ""),
        height=120,
        placeholder="Например: машинист допущен к управлению без свидетельства"
    )

with col2:
    st.markdown("&nbsp;")
    find_clicked = st.button("🔍 Найти пункт", type="primary", use_container_width=True)
    
with col2:
    st.markdown("&nbsp;")
    formal_clicked = st.button("📝 Сформировать замечание", type="primary", use_container_width=True)

st.markdown("---")

if find_clicked and remark.strip():
    with st.spinner("Анализируем замечание..."):
        result = rag_system.find_violation(remark)
    
    st.session_state.last_result = result
    st.session_state.show_result = True
    st.session_state.formal_remark = None
    st.session_state.selected_punkt = None

if st.session_state.get("show_result", False) and "last_result" in st.session_state:
    result = st.session_state.last_result
    
    st.markdown("### Результат анализа")
    
    col_meta, col_method = st.columns([2, 1])
    
    with col_meta:
        if result.get("rule_info"):
            rule_info = result["rule_info"]
            st.markdown(f"**Раздел:** {rule_info.get('section_desc', 'N/A')}")
            st.markdown(f"**Правило:** {rule_info.get('rule_text', 'N/A')}")
    
    with col_method:
        method_labels = {
            "KEYWORD": "✅ Точное совпадение",
            "FUZZY": "🔍 Fuzzy поиск", 
            "NEED_SELECTION": "📋 Требуется выбор",
            "NOT_FOUND": "❌ Не найдено"
        }
        st.markdown(f"**Метод:** {method_labels.get(result['method'], result['method'])}")
    
    st.markdown("---")
    
    if result["method"] == "NEED_SELECTION" and result.get("candidates"):
        st.markdown("#### Выберите подходящий пункт:")
        
        candidates = result["candidates"]
        options = [f"**{c['punkt']}** — {c.get('description', '')[:80]}..." if c.get('description') else c['punkt'] for c in candidates]
        
        selected_idx = st.radio(
            "Кандидаты:",
            options=range(len(options)),
            format_func=lambda i: options[i],
            label_visibility="collapsed"
        )
        
        st.markdown("---")
        
        col_confirm, col_cancel = st.columns(2)
        with col_confirm:
            if st.button("✅ Подтвердить выбор", type="primary", use_container_width=True):
                selected_candidate = candidates[selected_idx]
                st.session_state.selected_punkt = selected_candidate["punkt"]
                st.session_state.last_result["result"] = selected_candidate["punkt"]
                
                full_text = rag_system.get_punkt_full_text(selected_candidate["punkt"])
                st.session_state.last_result["full_text"] = full_text
                
                st.session_state.last_result["method"] = "SELECTED"
                st.success(f"Выбран: {selected_candidate['punkt']}")
                st.rerun()
        
        with col_cancel:
            if st.button("❌ Отмена", use_container_width=True):
                st.session_state.selected_punkt = None
                st.session_state.show_result = False
                st.rerun()
    
    elif result["result"] and result["result"] != "НЕ ОПРЕДЕЛЕНО":
        st.markdown(f"#### Найденный пункт:")
        st.success(f"**{result['result']}**")
        
        if st.button("📝 Сформировать официальное замечание", type="primary"):
            with st.spinner("Формируем замечание..."):
                formal = rag_system.generate_formal_remark(remark, result["result"])
            st.session_state.formal_remark = formal
    
    else:
        st.error("❌ Пункт не определен. Попробуйте переформулировать замечание.")

if st.session_state.get("formal_remark"):
    st.markdown("---")
    st.markdown("### 📋 Официальное замечание")
    st.markdown(f"""
    <div style="background-color: #e8f5e9; padding: 20px; border-radius: 10px; border-left: 5px solid #4caf50;">
    <p style="font-size: 16px; line-height: 1.6; margin: 0;">{st.session_state.formal_remark}</p>
    </div>
    """, unsafe_allow_html=True)
    
    col_copy, col_clear = st.columns(2)
    with col_copy:
        st.code(st.session_state.formal_remark, language=None)
        st.caption("Скопируйте текст выше")
    
    with col_clear:
        if st.button("🗑️ Очистить", use_container_width=True):
            st.session_state.formal_remark = None
            st.session_state.show_result = False
            st.session_state.last_result = None
            st.session_state.selected_punkt = None
            st.session_state.remark_input = ""
            st.rerun()

if st.session_state.get("last_result") and st.session_state.last_result.get("full_text"):
    with st.expander("📖 Полный текст пункта", expanded=False):
        st.text(st.session_state.last_result["full_text"])

if not st.session_state.get("show_result", False):
    st.info("👆 Введите замечание и нажмите 'Найти пункт' для анализа")