# datos-externos

Respaldo semanal de fuentes que bloquean a los servidores de GitHub (Davivienda, Bancolombia).
Lo genera una tarea programada de Claude con `python run_all.py --fuentes davivienda,bancolombia --exportar data/externos`.
Lo lee .github/workflows/actualizar.yml en main.
