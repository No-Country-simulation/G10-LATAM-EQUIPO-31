# MF-33 — Conexión local por 127.0.0.1 por defecto

Issue: #69 · Rama: `fix/MF-33-api-url-ipv4` · Base: `develop` (`b5f991a`, con el PR #68 integrado)

## 1. Objetivo y alcance

Con la API local apagada, el panel tarda ~30 s en avisar. Kimberlyn lo dejó como observación no bloqueante en la revisión de MF-30 y propuso usar `127.0.0.1` como valor por defecto en local, manteniendo la URL configurable y los reintentos. Mauricio midió la causa (ver §3).

**Fuera de alcance (deliberadamente):**

| No se hace | Motivo |
|---|---|
| Cambiar los reintentos | Se conserva la tolerancia al arranque de la API |
| Separar `connect_timeout` y `read_timeout` (propuesta de Jennifer) | Se decide aparte, con mediciones |
| Cambiar la lógica de Carga, Consulta o Revisión humana | El cambio solo es el valor por defecto de la URL |

## 2. Qué se cambió

| Archivo | Cambio |
|---|---|
| `frontend/utils_frontend.py` | Valor por defecto de `API_BASE_URL` y su docstring: `http://127.0.0.1:8000` en lugar de `http://localhost:8000` |
| `docs/MF-12-hitl-review.md` | Valor por defecto de `MEDIFLOW_API_URL` |
| `docs/MF-28-interfaz-amigable-de-entrada.md` | URL que muestra el aviso de API apagada |

La variable `MEDIFLOW_API_URL` sigue teniendo prioridad: si está definida, el valor por defecto no se usa.

## 3. Causa

Con la API apagada, el cliente hace 5 intentos (el primero y 4 reintentos) con esperas de 0, 1,4, 2,8 y 5,6 s (~9,8 s en total). En Windows, `localhost` prueba primero IPv6 (`::1`) y luego IPv4 (`127.0.0.1`), y cada rechazo tarda ~2 s: ~4 s por intento con `localhost` y ~2 s con `127.0.0.1`.

## 4. Mediciones (Windows)

| Medición | Con `localhost` | Con `127.0.0.1` |
|---|---|---|
| Panel real (`utils_frontend._solicitar`), API apagada | 30,23 s | 19,99 s |
| Un rechazo de conexión suelto, API apagada | 4,13 s | 2,08 s |
| Una conexión nueva con un servicio escuchando en el puerto 8000 | 2,16 s | 0,04 s |

Cada valor es una sola medición en un equipo Windows. Coinciden con las de Mauricio en la revisión de MF-30 (31 s en el panel; 4,09 s y 2,03 s por rechazo).

## 5. Qué se conserva

- Número de reintentos, esperas y mensaje de error: iguales.
- URL configurable con `MEDIFLOW_API_URL`.
- Resto del frontend y la API.

## 6. Límites del cambio

- La espera baja de ~30 s a ~20 s, no desaparece. El piso son las esperas entre reintentos (~9,8 s) y los ~2 s por rechazo.
- En Linux o Docker el rechazo en `localhost` suele ser casi instantáneo, así que allí la mejora sería pequeña.
- En Docker, entre contenedores no se usa `127.0.0.1` sino el nombre del servicio: hay que fijar `MEDIFLOW_API_URL`.
- Si alguien levanta la API solo en IPv6, hay que definir `MEDIFLOW_API_URL`.
- No hay credenciales de OCI en este entorno, así que los flujos completos con la API encendida no se probaron a mano. Las pruebas automáticas los cubren con datos simulados.

## 7. Pruebas automatizadas

`python -m pytest` → **342 pasan**, antes y después del cambio. No se añadieron pruebas: los mocks de `tests/` escriben `localhost:8000` a mano y no leen `API_BASE_URL`.

## 8. Criterios de aceptación

| Criterio del ticket | Estado |
|---|---|
| El frontend usa `127.0.0.1` por defecto en local | Cumplido (§2; la medición del panel muestra `URL: http://127.0.0.1:8000`) |
| Se mantiene la posibilidad de configurar otra URL | Cumplido (`MEDIFLOW_API_URL` sigue mandando; se usó para medir el «antes») |
| No cambia el comportamiento de los reintentos | Cumplido (§5) |
| Se documentan las mediciones antes y después | Cumplido (§4 y evidencias) |
| Las pruebas automatizadas siguen pasando | Cumplido (§7, 342) |

## 9. Evidencias

Carpeta `docs/assets/sprint-4/mf-33-api-url-ipv4/`:

| Escenario | Archivo | Estado |
|---|---|---|
| Medición antes y después con el cliente real | [evidencia-medicion-antes-despues.png](./assets/sprint-4/mf-33-api-url-ipv4/evidencia-medicion-antes-despues.png) | OK |
| API apagada: Carga | [evidencia-api-apagada-carga.png](./assets/sprint-4/mf-33-api-url-ipv4/evidencia-api-apagada-carga.png) | OK |
| API apagada: Consulta | [evidencia-api-apagada-consulta.png](./assets/sprint-4/mf-33-api-url-ipv4/evidencia-api-apagada-consulta.png) | OK |
| API apagada: Revisión humana | [evidencia-api-apagada-revision-humana.png](./assets/sprint-4/mf-33-api-url-ipv4/evidencia-api-apagada-revision-humana.png) | OK |

## 10. Cómo probarlo

```powershell
python -m pytest -q
streamlit run frontend/mediflow.py
```

Con la API apagada, abre Carga, Consulta y Revisión humana: el aviso debe mostrar `http://127.0.0.1:8000`. Para volver al comportamiento anterior: `$env:MEDIFLOW_API_URL = "http://localhost:8000"`.