"""RAG система для поиска нарушений ПТЭ/ИДП.

Новая архитектура:
1. Keyword search -> точный результат
2. Fuzzy search -> точный результат  
3. LLM candidates -> выбор пользователя
4. LLM formal remark -> финальное замечание
"""

import re
import requests
from pathlib import Path
from docx import Document
from config import (
    DOCX_PATH, MINMAX_URL, MINMAX_MODEL,
    CHUNK_SIZE, CHUNK_OVERLAP, API_TIMEOUT, TEMPERATURE, MAX_TOKENS
)
from rules import (
    find_by_keywords, find_rule, find_rule_by_punkt, get_all_rules,
    SECTION_RULES, get_sections_summary
)


class PTERAGSystem:
    def __init__(self):
        self.chunks = []
        self.full_text = ""
        self._load_document()
    
    def _load_document(self):
        """Загрузка и разбиение документа на чанки."""
        doc = Document(DOCX_PATH)
        self.full_text = "\n".join([para.text for para in doc.paragraphs])
        
        from langchain_text_splitters import RecursiveCharacterTextSplitter
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
            separators=["\n\n", "\n", "Раздел", "Приложение"]
        )
        self.chunks = splitter.split_text(self.full_text)
    
    def find_violation(self, remark):
        """Основной метод поиска нарушения.
        
        Алгоритм:
        1. Точный keyword search -> result
        2. Fuzzy search -> result  
        3. LLM candidates -> NEED_SELECTION
        4. Ничего не найдено -> NOT_FOUND
        """
        # 1. Пробуем точный поиск по ключевым словам
        keyword_result = find_by_keywords(remark)
        if keyword_result:
            full_punkt_text = self._get_full_punkt_text(keyword_result)
            rule_info = find_rule(keyword_result)
            return {
                "result": keyword_result,
                "candidates": [],
                "method": "KEYWORD",
                "full_text": full_punkt_text,
                "rule_info": rule_info
            }
        
        # 2. Fuzzy search по всем правилам
        fuzzy_result = self._fuzzy_search(remark)
        if fuzzy_result:
            full_punkt_text = self._get_full_punkt_text(fuzzy_result)
            rule_info = find_rule(fuzzy_result)
            return {
                "result": fuzzy_result,
                "candidates": [],
                "method": "FUZZY",
                "full_text": full_punkt_text,
                "rule_info": rule_info
            }
        
        # 3. LLM для поиска кандидатов
        candidates = self._find_candidates_llm(remark)
        if candidates:
            return {
                "result": None,
                "candidates": candidates,
                "method": "NEED_SELECTION",
                "full_text": None,
                "rule_info": None
            }
        
        # 4. Ничего не найдено
        return {
            "result": "НЕ ОПРЕДЕЛЕНО",
            "candidates": [],
            "method": "NOT_FOUND",
            "full_text": None,
            "rule_info": None
        }
    
    def _fuzzy_search(self, remark, threshold=0.3):
        """Поиск по всем правилам с fuzzy matching."""
        remark_lower = remark.lower()
        remark_words = set(remark_lower.split())
        
        best_match = None
        best_score = 0
        
        for rule in get_all_rules():
            rule_keywords = set(rule.keywords)
            intersection = remark_words & rule_keywords
            
            # Score based on keyword overlap
            if intersection:
                score = len(intersection) / max(len(rule_keywords), 1)
                
                # Bonus for multi-word keyword matches
                for kw in rule.keywords:
                    if kw in remark_lower:
                        score += 0.2
                        if len(kw.split()) > 1:
                            score += 0.1
                
                if score >= threshold and score > best_score:
                    best_match = rule.punkt
                    best_score = score
        
        return best_match
    
    def _find_candidates_llm(self, remark, top_k=5):
        """Запрос к LLM для поиска топ-K кандидатов."""
        try:
            sections_map = get_sections_summary()
            
            prompt = f"""ЗАДАЧА: По замечанию найди {top_k} самых подходящих пунктов ПТЭ или ИДП.

ЗАМЕЧАНИЕ: {remark}

СПРАВОЧНИК:
ПТЭ Раздел 2: Работники, свидетельства, медосмотры
ПТЭ Раздел 6: Светофоры, видимость
ПТЭ Раздел 9: Подвижной состав, локомотивы, тормоза
ИДП Приложение 6: Разграничение временем
ИДП Приложение 9: Прием/отправление поездов
ИДП Приложение 10: Маневровая работа
ИДП Приложение 12: Закрепление башмаками
ИДП Приложение 14: Замыкание стрелок

ОТВЕТЬ ТОЛЬКО В ФОРМАТЕ:
1. Раздел 2 пункт 9 ПТЭ
2. Приложение 14 пункт 15 ИДП

БОЛЬШЕ НИЧЕГО НЕ ПИШИ. НЕ ОБЪЯСНЯЙ. НЕ ИСПОЛЬЗУЙ <think>."""
            
            response = requests.post(
                MINMAX_URL,
                json={
                    "model": MINMAX_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 300
                },
                timeout=API_TIMEOUT
            )
            
            if response.status_code == 200:
                content = self._clean_thinking(response.json()["choices"][0]["message"]["content"])
                return self._parse_candidates(content, top_k)
        except Exception:
            pass
        return []
    
    def _parse_candidates(self, text, top_k):
        """Парсинг кандидатов из текста."""
        candidates = []
        
        # Фильтруем thinking content
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
        
        lines = text.strip().split('\n')
        
        for line in lines:
            # Пропускаем пустые строки и строки с thinking
            if not line.strip() or '<think>' in line.lower():
                continue
            
            # Убираем номер и точку в начале (1., 2., etc)
            clean_line = re.sub(r'^\d+[\.\)]\s*', '', line.strip().lower())
            
            # Ищем пункт
            match = re.search(
                r'(раздел\s+\d+\s+пункт\s+\d+\s+птэ|приложение\s+\d+\s+пункт\s+\d+\s+идп)',
                clean_line
            )
            if match:
                punkt = match.group(1).upper()
                rule_info = find_rule_by_punkt(punkt)
                candidates.append({
                    "punkt": punkt,
                    "description": rule_info.rule_text if rule_info else "",
                    "section": rule_info.section_desc if rule_info else ""
                })
            
            if len(candidates) >= top_k:
                break
        
        return candidates
    
    def _get_full_punkt_text(self, punkt_name):
        """Получение полного текста пункта из документа."""
        if not punkt_name or punkt_name == "НЕ ОПРЕДЕЛЕНО":
            return None
        
        # Нормализуем для поиска
        punkt_normalized = punkt_name.lower().replace("птэ", "").replace("идп", "").strip()
        
        # Ищем в тексте документа
        pattern = re.compile(
            punkt_normalized.replace(" ", r"\s+") + r"[\s\.\—].*?(?=\n\n|раздел\s+\d+|приложение\s+\d+|$)",
            re.IGNORECASE | re.DOTALL
        )
        
        match = pattern.search(self.full_text)
        if match:
            return match.group(0).strip()
        
        # Fallback: ищем в чанках
        for chunk in self.chunks:
            normalized_chunk = chunk.lower().replace(" ", "")
            normalized_punkt = punkt_normalized.replace(" ", "")
            if normalized_punkt in normalized_chunk:
                if "раздел" in chunk.lower() or "приложение" in chunk.lower():
                    return chunk.strip()
        
        return None
    
    def generate_formal_remark(self, remark, punkt_name):
        """Генерация официального замечания в деловом стиле."""
        if not punkt_name or punkt_name == "НЕ ОПРЕДЕЛЕНО":
            return "Не удалось определить пункт нарушения"
        
        safe_remark = remark.replace('"', '\\"').replace("'", "\\'")
        safe_punkt = punkt_name.replace('"', '\\"').replace("'", "\\'")
        
        # Получаем информацию о правиле
        rule_info = find_rule(punkt_name)
        rule_desc = rule_info.get("rule_text", "") if rule_info else ""
        
        prompt = f"""Сформируй официальное замечание о нарушении требований нормативного документа.

ЗАМЕЧАНИЕ: {safe_remark}
ПУНКТ: {safe_punkt}
{"ОПИСАНИЕ ПРАВИЛА: " + rule_desc if rule_desc else ""}

Требования к формату:
- Начинается с "В нарушение требований"
- Содержит номер пункта
- Описывает нарушение в официальном деловом стиле
- Одно предложение

Примеры правильного стиля:
- "В нарушение требований Раздел 2 пункт 9 ПТЭ машинист допущен к управлению локомотивом без наличия свидетельства о праве на управление"
- "В нарушение требований Приложение 14 пункт 15 ИДП не обеспечено замыкание стрелочного перевода при движении поездов по запрещающим показаниям светофоров"

Напиши ТОЛЬКО одно предложение, начинающееся с "В нарушение требований":"""
        
        try:
            response = requests.post(
                MINMAX_URL,
                json={
                    "model": MINMAX_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 400
                },
                timeout=API_TIMEOUT
            )
            
            if response.status_code == 200:
                content = response.json()["choices"][0]["message"]["content"]
                return self._clean_thinking(content).strip()
            else:
                return f"ОШИБКА: {response.status_code}"
        except Exception as e:
            return f"ИСКЛЮЧЕНИЕ: {str(e)}"
    
    def get_punkt_full_text(self, punkt_name):
        """Публичный метод для получения текста пункта."""
        return self._get_full_punkt_text(punkt_name)
    
    @staticmethod
    def _clean_thinking(text):
        """Очистка текста от разметки think - берём последний </think> блок."""
        if '<think>' not in text:
            return text.strip()
        
        parts = text.split('</think>')
        if len(parts) > 1:
            after_last = parts[-1].strip()
            if after_last:
                return after_last
        
        return text.strip()
    
    @staticmethod
    def normalize_punkt(text):
        """Нормализация названия пункта."""
        text = text.lower().strip()
        text = re.sub(r'[№#]', '', text)
        text = re.sub(r'приложения?\s*(\d+)', r'приложение \1', text)
        text = re.sub(r'раздел\s+(\d+)', r'раздел \1', text)
        text = re.sub(r'пункт\s+(\d+)', r'пункт \1', text)
        text = re.sub(r'п\.', 'пункт', text)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()


# Глобальный экземпляр
rag_system = PTERAGSystem()