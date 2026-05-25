# Frontend — Comentarios sobre el reporte (internos / externos)

Guía para integrar los nuevos endpoints de comentarios en la vista de detalle de reporte (panel funcionario y vista del vecino).

**Endpoints nuevos** (spec autoritativa: [`api.md`](./api.md) §4.28 y §4.29):

- `POST /api/v1/reportes/{id}/comentarios` — agrega un comentario.
- `GET  /api/v1/reportes/{id}/comentarios` — lista los comentarios del reporte (filtrados según rol).

**Cambio compatible** en `GET /api/v1/reportes/{id}` (§4.8): la respuesta ahora incluye un array `comentarios` ya filtrado según el rol del caller. No se rompe ningún cliente que lo ignore.

**Modelo de datos** (resumen — detalle en [`bbdd.md`](./bbdd.md) §3.8):

| Campo | Tipo | Notas |
|---|---|---|
| `id` | int | Identifica el comentario. |
| `visibilidad` | `"interno"` / `"externo"` | Interno: solo funcionarios. Externo: también el vecino. |
| `cuerpo` | string (1–2000) | Texto del comentario. |
| `autor` | `{ id, nombre }` | Quién lo escribió. |
| `delegado_a` | `{ id, nombre }` o `null` | Funcionario al que se delegó (solo internos). |
| `delegado_at` | ISO 8601 o `null` | Cuándo aplica la delegación. |
| `created_at` | ISO 8601 | Timestamp del comentario. |

---

## 1. Reglas de UI

### 1.1 Vista de detalle del reporte — panel funcionario

Agregar al detalle del reporte un **bloque "Comentarios"** debajo del historial de estados. Dos sub-bloques colapsables o pestañas:

- **Externos** (mensajes al vecino) — siempre visibles.
- **Internos** (entre el equipo de la municipalidad / admin) — visibles solo si el caller es `municipalidad` o `admin`.

Cada item muestra:

- Cuando es delegación: badge **"Delegación"** + texto rico `"{autor.nombre} delegó a {delegado_a.nombre} — {delegado_at formateado}"` arriba del `cuerpo`.
- Cuando no: solo `autor.nombre` + `created_at` (relativo, "hace 3 min") y el `cuerpo`.

### 1.2 Vista del vecino (dueño del reporte)

En "Mis reportes" → detalle: mostrar solamente el bloque **Externos** como un timeline. El back ya filtra; el front no necesita lógica extra de filtro.

**Empty state:** "Aún no hay actualizaciones del municipio sobre este reporte." (en lugar de un array vacío silencioso).

### 1.3 Formulario para agregar comentario (solo funcionarios)

Botón "Agregar comentario" abre un modal con dos modos seleccionables al inicio:

```
┌─ ¿Qué tipo de comentario querés agregar? ─┐
│                                           │
│   ( ) Mensaje al vecino                   │
│       Será visible para quien creó         │
│       el reporte.                          │
│                                           │
│   (•) Nota interna                        │
│       Solo lxs funcionarixs lo ven.       │
│                                           │
└───────────────────────────────────────────┘
```

#### Modo "Mensaje al vecino" → `visibilidad: "externo"`

- **Textarea** (`cuerpo`, requerido, 1–2000 chars).
- No hay campos de delegación.

#### Modo "Nota interna" → `visibilidad: "interno"`

- **Textarea** (`cuerpo`, requerido).
- **Checkbox "Esta nota es una delegación"** → al activarlo:
  - **Selector de funcionario** (`delegado_a_id`): dropdown poblado con los usuarios `tipo='municipalidad'` de la misma comuna. La fuente recomendada es `GET /api/v1/usuarios?tipo=municipalidad&comuna_id={comuna_del_reporte}` (endpoint admin-only — si el front actual no lo tiene cacheado, se puede invocar al abrir el modal y cachearlo en memoria).
  - **Input de fecha+hora** (`delegado_at`): default a "ahora" pero editable (datetime-local picker). Convertir a ISO 8601 UTC al enviar.

**Validaciones del lado del cliente** (espejo del backend para evitar round-trips):

- `cuerpo` no puede ser solo espacios.
- Si checkbox de delegación: `delegado_a_id` y `delegado_at` son ambos requeridos.
- Si el modo es "externo": el checkbox de delegación queda oculto (no aplica).

---

## 2. Cliente HTTP

`src/services/reporteComentarios.ts`:

```ts
import { http } from "./http";

export interface UsuarioRef { id: string; nombre: string; }

export interface Comentario {
  id: number;
  visibilidad: "interno" | "externo";
  cuerpo: string;
  autor: UsuarioRef;
  delegado_a: UsuarioRef | null;
  delegado_at: string | null;  // ISO 8601 UTC
  created_at: string;          // ISO 8601 UTC
}

export interface CrearComentarioBody {
  visibilidad: "interno" | "externo";
  cuerpo: string;
  delegado_a_id?: string;
  delegado_at?: string;   // ISO 8601 UTC
}

export async function listarComentarios(reporteId: string): Promise<Comentario[]> {
  const { data } = await http.get(`/reportes/${reporteId}/comentarios`);
  return data.data;
}

export async function crearComentario(
  reporteId: string,
  body: CrearComentarioBody,
): Promise<Comentario> {
  const { data } = await http.post(`/reportes/${reporteId}/comentarios`, body);
  return data;
}
```

---

## 3. Estados de error y feedback

| Status | Significado | UI sugerida |
|---|---|---|
| `401 unauthorized` | Token vencido. | Forzar logout / refresh. |
| `403 forbidden` o `comuna_mismatch` | El funcionario no es de la comuna del reporte. | Toast "No tenés permiso para comentar este reporte." |
| `404 reporte_not_found` | El reporte fue eliminado. | Redirigir a "Mis reportes" / panel. |
| `422 validation_error` | Cuerpo vacío, delegación incompleta, `delegado_a_id` no es funcionario. | Marcar el campo en rojo. Texto del backend en `detail`. |

---

## 4. Checklist de QA

- [ ] Vecino dueño del reporte: ve solo externos. No ve el botón "Agregar comentario".
- [ ] Funcionario de la comuna: ve internos + externos y puede agregar de ambos tipos.
- [ ] Funcionario de otra comuna: 403 al intentar listar o agregar.
- [ ] Admin: como funcionario, sin restricción de comuna.
- [ ] Delegación: el comentario muestra el badge "Delegación" + el funcionario y la hora.
- [ ] Si elegís "externo" + click en checkbox delegación: el checkbox no aparece (validar UI condicional).
- [ ] Al crear un comentario, el detalle del reporte se refresca y el nuevo item aparece al final del array.
