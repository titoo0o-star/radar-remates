# Radar de Remates — Instrucciones para Claude Code

## Contexto
Quiero encontrar **apartamentos y locales comerciales para flipear**: comprar por debajo del mercado, remodelar y revender.
El proyecto tiene dos partes:
1. **Scrapers** que juntan inmuebles en remate y en venta directa de bancos y entidades en un solo archivo (`remates.json` y `remates.csv`).
2. **Una app web** con mapa y tabla sincronizados para explorar esos inmuebles.

Empieza un proyecto nuevo en esta carpeta, con git.

## Alcance
- **Tipos:** solo apartamentos y locales comerciales. Descarta todo lo demás antes de guardar (casas, lotes, bodegas, fincas, vehículos).
- **Ciudades:** Bogotá, Medellín, Cali, Barranquilla, Cartagena y Bucaramanga, cada una con su área metropolitana. Descarta lo que esté fuera.
- **Modalidades:** subasta, puja electrónica y venta directa, todas en el mismo ranking.
- **Métrica principal:** margen frente al mercado (`margen_pct`), no el descuento frente al avalúo. El avalúo es solo un dato de referencia.

---

## Fase 1 — Scrapers + referencia de mercado

### Fuentes
| Fuente | URL | Método sugerido | Notas |
|---|---|---|---|
| SAE | https://activosporcolombia.com/es/v2/buscar?operator_ids=2 | Playwright | ~6.000 inmuebles, paginado. Detalle en `/es/inmueble/{id}/{slug}` o `/es/unidad-inmobiliaria/{id}/{slug}`. El filtro por tipo funciona dentro de la página, no por URL. Publica dos precios sin etiqueta clara: revisa en la ficha de detalle cuál es el precio base y cuál el avalúo. |
| Bancolombia | Sección "Venta de usados" de bancolombia.com y tu360inmobiliario.bancolombia.com | Descargar el Excel | Usa "Continúa explorando bienes en venta" → "Descargar excel" en vez de scrapear el HTML. Venta directa, sin avalúo. La dirección exacta a veces no se publica. |
| CISA | https://inmuebles.cisa.gov.co | Playwright, o la API interna (revisa las peticiones de red) | El HTML estático no trae los datos. Incluye inmuebles de la DIAN y otras entidades. Puja electrónica. |
| Davivienda | https://bienesalalcancedetodos.davivienda.com | HTML o Playwright | Dación en pago y remates. |

### Referencia de precio de mercado
- Scraper de anuncios de **Fincaraíz y Metrocuadrado** para apartamentos y locales en las 6 ciudades.
- Resúmelos en `data/mercado.json`: la **mediana del precio/m²** por ciudad, barrio y tipo, con el número de anuncios que la sostienen.
- Si un barrio tiene menos de 5 anuncios, usa la mediana de la ciudad y márcalo.

### Esquema de salida (un objeto por inmueble)
| Campo | Tipo | Regla |
|---|---|---|
| `id` | texto | `{fuente}:{codigo}`, único en todo el dataset |
| `fuente` | texto | sae, bancolombia, cisa, davivienda (luego: martillo, dian, agrario, bbva, contraloria, rama) |
| `codigo` | texto | Código del portal |
| `matricula` | texto o null | Folio de matrícula inmobiliaria, sin espacios. Llave para quitar duplicados |
| `titulo` | texto | Descripción corta |
| `tipo` | texto | `apartamento` o `local` |
| `ciudad`, `departamento`, `barrio` | texto o null | Nombres normalizados |
| `direccion` | texto o null | Tal como la publica el portal |
| `lat`, `lon` | número o null | Ver "Ubicación" en la fase 2 |
| `precision_ubicacion` | texto | `exacta`, `barrio` o `ciudad` |
| `area_m2` | número o null | Área construida; si no hay, área privada |
| `precio_compra` | entero COP | Precio de venta directa o postura mínima |
| `precio_m2` | entero o null | precio_compra ÷ area_m2 |
| `precio_m2_mercado` | entero o null | Mediana de comparables (misma ciudad, barrio y tipo) |
| `margen_pct` | decimal o null | 1 − precio_m2 ÷ precio_m2_mercado |
| `comparables_n` | entero | Anuncios detrás de la mediana |
| `avaluo` | entero COP o null | Solo referencia |
| `modalidad` | texto | `subasta`, `puja_electronica` o `venta_directa` |
| `fecha_subasta` | AAAA-MM-DD o null | Null en venta directa |
| `estado_ocupacion` | texto | `ocupado`, `desocupado` o `sin_dato` |
| `url` | texto | Link a la ficha del inmueble |
| `fecha_scrapeo` | AAAA-MM-DD | Día de la extracción |

Precios en pesos como número entero, sin formato.

### Margen neto estimado (configurable)
Además de `margen_pct`, calcula `margen_neto_pct` con supuestos que yo pueda cambiar en `config.yaml`:
- `impuesto_remate`: 5% del precio, solo en remates judiciales
- `escritura_registro`: 2% del precio de compra
- `remodelacion`: 10% del valor de mercado
- `tenencia_meses`: 6, con un costo mensual de 0,25% del valor de mercado
- `descuento_cierre`: 5% (el precio de cierre queda por debajo del de anuncio)
- `comision_venta`: 3% del precio de venta

### Arquitectura
```
radar-remates/
├── scrapers/        # un archivo por fuente, todos devuelven el mismo esquema
├── mercado/         # scraper de Fincaraíz/Metrocuadrado y cálculo de medianas
├── run_all.py       # corre todo, normaliza, quita duplicados, calcula márgenes, valida
├── config.yaml      # supuestos de costos y lista de ciudades
├── data/            # remates.json, remates.csv, mercado.json, historial por fecha
├── logs/
└── app/             # la app de la fase 2
```

### Reglas
- Un módulo por fuente. Si una fuente falla, las demás siguen y la falla queda en el log.
- Quita duplicados por matrícula cuando exista (por ejemplo, un inmueble de la SAE que también aparece en CISA).
- Deja 1–2 s entre peticiones y usa un user-agent normal.
- Alerta en el log si una fuente trae menos de la mitad de las filas de la corrida anterior.
- Guarda cada corrida con fecha en `data/historial/`.

### Orden de trabajo
1. Empieza con **una sola fuente** (la SAE) y prueba con 20 inmuebles.
2. Muéstrame 5 filas de cada fuente antes de correrla completa.
3. Al final, dame un resumen por fuente: total de inmuebles, % con área, % con `margen_pct` (y con 5+ comparables), % con dirección, y los campos que no se pudieron extraer.

**Listo cuando:** las 4 fuentes corren sin intervención, ≥ 95% de las filas tienen `precio_compra`, `area_m2`, `ciudad` y `url`, y ≥ 70% tienen `margen_pct` con 5+ comparables.

---

## Fase 2 — App de mapa + tabla
Empieza esta fase cuando la fase 1 esté lista.

### Concepto
Un mapa y una tabla que comparten **el mismo estado de filtros**: lo que filtro u ordeno en la tabla es exactamente lo que aparece en el mapa.

### Pantalla
- **Computador:** el mapa a la izquierda (~60%) y la tabla a la derecha, visibles al mismo tiempo.
- **Celular:** pestañas Mapa y Tabla, con los filtros arriba compartidos entre las dos.
- **Selector de ciudad:** las 6 ciudades del alcance, cada una con su área metropolitana.

### Sincronización
- Filtros: tipo, margen mínimo, rango de precio, área, modalidad, fuente, barrio, y ocultar ocupados.
- Filtrar u ordenar la tabla actualiza los pines del mapa al instante.
- Tocar una fila centra el mapa en ese pin y lo resalta. Tocar un pin resalta su fila y abre la ficha.
- Botón "Solo esta zona": al moverme por el mapa, la tabla muestra solo lo visible. Se puede apagar.
- Los filtros quedan en la URL, para guardar o compartir una vista.

### Volumen (miles de inmuebles)
- Pines agrupados en círculos con el conteo, que se separan al acercarse (Leaflet.markercluster).
- La tabla carga por partes al hacer scroll.
- Un contador visible, por ejemplo "312 de 4.870 inmuebles".

### Mapa
- Color del pin según el margen: verde ≥ 40%, amarillo 30–40%, gris < 30%. Forma según el tipo (apartamento o local).
- Pin hueco cuando la ubicación es aproximada.
- Capa opcional: precio/m² mediano por barrio en colores.
- Ficha al tocar un pin: precio, m², margen, margen neto, comparables, modalidad, fecha de subasta, ocupación y link al portal.

### Ubicación
- Intenta ubicar la dirección exacta (Nominatim/OpenStreetMap, respetando su límite de 1 petición por segundo). Si falla, usa el centro del barrio; si tampoco, el de la ciudad.
- Guarda `precision_ubicacion`.
- Guarda en caché los resultados por dirección (`data/geocache.json`), para no repetir la búsqueda cada semana.

### Tecnología
- Página web estática (HTML/JS) con Leaflet y mapas de OpenStreetMap: sin costo ni API key.
- Lee `data/remates.json`.
- Publicada en GitHub Pages, para abrirla desde el celular.

**Listo cuando:** todos los inmuebles de la fase 1 cargan en menos de 3 s, filtrar la tabla actualiza el mapa sin recargar, y ≥ 80% de los pines tienen ubicación exacta o de barrio.

---

## Fases siguientes (deja la estructura lista; no las construyas aún)
3. **Más fuentes:**
   - El Martillo (elmartillo.com.co): requiere registro; las credenciales van en variables de entorno, y hay que filtrar solo inmuebles.
   - DIAN (rematesvirtuales.dian.gov.co).
   - Banco Agrario: prioridad baja, porque casi todo su inventario es rural.
   - BBVA: catálogo en PDF.
   - Contraloría.
4. **Juzgados de la Rama Judicial:** un scraper genérico para los micrositios "Remates en línea" de las 6 ciudades, empezando por los juzgados civiles de Bogotá.
5. **Actualización semanal automática:** marca los inmuebles nuevos y los que salieron.
