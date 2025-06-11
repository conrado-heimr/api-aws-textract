# utils/text_sanitizer.py

import re

def sanitize_text_for_sql(text: str) -> str:
    """
    Remove caracteres não imprimíveis e nulos do texto,
    e substitui quebras de linha por espaços para compatibilidade com SQL Server.
    
    Args:
        text (str): O texto a ser sanitizado.

    Returns:
        str: O texto sanitizado.
    """
    # 1. Remove caracteres nulos (U+0000)
    cleaned_text = text.replace('\x00', '')

    # 2. Substitui quebras de linha (\n, \r) e tabulações (\t) por um espaço
    # Isso garante que o texto fique em uma única linha lógica para o SQL,
    # mantendo a separação entre as palavras.
    cleaned_text = re.sub(r'[\n\r\t]', ' ', cleaned_text)

    # 3. Remove outros caracteres de controle ASCII não imprimíveis
    # (ex: \x01 a \x08, \x0B, \x0C, \x0E a \x1F, \x7F)
    cleaned_text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', cleaned_text)
    
    # Opcional: Remover múltiplos espaços consecutivos por um único espaço
    cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()

    return cleaned_text
