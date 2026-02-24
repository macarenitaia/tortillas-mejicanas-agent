from crew_logic import run_odoo_crew
import uuid

def main():
    print("--- Agente de Integración Odoo Activo ---")
    session_id = str(uuid.uuid4())
    
    while True:
        user_message = input("\nUsuario: ")
        if user_message.lower() in ['salir', 'exit', 'quit']:
            break
            
        print("\n[Procesando con CrewAI...]")
        result = run_odoo_crew(session_id, user_message)
        
        print(f"\nAgente: {result}")

if __name__ == "__main__":
    main()
