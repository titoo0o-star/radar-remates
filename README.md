# Radar de Remates

Apartamentos y locales en remate y venta directa (SAE, CISA, Davivienda) en Bogotá, Medellín,
Cali, Barranquilla, Cartagena y Bucaramanga (con sus áreas metropolitanas), ordenados por
**margen frente al mercado**.

## Uso

```bash
pip install -r requirements.txt

# 1. Referencia de mercado (Fincaraíz + portal Tu360 de Bancolombia). ~80 min; mensual basta.
python -m mercado.actualizar

# 2. Remates de todas las fuentes -> data/remates.json y data/remates.csv (~40 min)
python run_all.py

# Recalcular márgenes tras cambiar costos en config.yaml (sin volver a scrapear)
python run_all.py --solo-margenes

# Probar una fuente con pocos inmuebles (escribe en data/prueba/)
python run_all.py --fuentes sae --limite 20 --prueba
```

## App

`app/` es una página estática (Leaflet + OpenStreetMap) que lee `data/remates.json`.
Localmente: `python -m http.server` en la raíz del repo y abrir `http://localhost:8000/app/`.
Se publica en GitHub Pages con `.github/workflows/pages.yml`.

## Cómo se calcula el margen

- `margen_pct = 1 − precio_m2 ÷ precio_m2_mercado`
- `precio_m2_mercado`: mediana de anuncios del mismo tipo, en este orden: mismo barrio (≥ 5
  anuncios) → a ≤ 1 km → a ≤ 2 km → mediana de la ciudad. Si hay suficientes, solo anuncios de
  tamaño parecido (0,5× a 2× el área). El nivel usado queda en `mercado_nivel`.
- `margen_neto_pct` descuenta los costos de `config.yaml` (escritura, impuesto de remate,
  remodelación, tenencia, descuento de cierre y comisión).
- `revisar` lista motivos para desconfiar de un margen (pocos comparables, tamaño atípico,
  precio sospechosamente bajo).

## Estructura

```
scrapers/   una fuente por archivo (sae, cisa, davivienda); todas devuelven el mismo esquema
mercado/    anuncios de mercado (fincaraiz, tu360) y cálculo de medianas
common/     HTTP con pausas, normalización, esquema, ubicación (Nominatim)
run_all.py  corre fuentes, valida, quita duplicados por matrícula, ubica, calcula márgenes
config.yaml costos, municipios del alcance, parámetros de mercado
data/       remates.json/.csv, mercado.json, barrios.json, geocache.json, historial/
app/        mapa + tabla
```
