import re

def normalize_phone(phone: str) -> str:
    """
    Normaliza un número de teléfono a formato E.164 básico.
    Elimina caracteres no numéricos (excepto el '+' inicial).
    Añade '+' si no lo tiene.
    Valida que tenga entre 6 y 15 dígitos.
    Lanza ValueError si es inválido.
    """
    if not phone:
        raise ValueError("Teléfono vacío")
        
    clean = re.sub(r'[^\d+]', '', phone)
    
    if clean.startswith('+'):
        number_part = clean[1:]
        prefix = '+'
    else:
        number_part = clean
        prefix = '+'
        
    number_part = re.sub(r'\D', '', number_part) # Asegurar solo dígitos en el resto
    
    if not 6 <= len(number_part) <= 15:
        raise ValueError(f"Teléfono inválido. Debe contener entre 6 y 15 dígitos. Obtenido: {clean}")
        
    return f"{prefix}{number_part}"
