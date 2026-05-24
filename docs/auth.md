# Autenticación y autorización — 40dB

Documento de **identidad, sesiones y autorización** del backend 40dB. Cubre cómo se registra un usuario, cómo se identifica en cada request, qué puede hacer cada rol, y por qué el backend bypassa RLS de Supabase.

**Documentos relacionados:**
- [`backend.md`](./backend.md) — ADR 02 (Supabase como persistencia + auth), ADR 07 (RLS bypass).
- [`bbdd.md`](./bbdd.md) — tabla `usuario`, trigger `handle_new_user`, máquina de estados.
- [`errores.md`](./errores.md) — 401/403, mapeo de errores de auth a HTTP *(pendiente)*.

---

## 1. Decisiones de diseño

| # | Decisión | Justificación |
|---|---|---|
| A1 | **Usamos Supabase Auth nativo**, no rolling-our-own | Supabase provee el flujo completo (signup, login, JWT, refresh, recuperación de password) sin código en el backend. Reinventarlo no aporta nada y aumenta superficie de bug. |
| A2 | **Email + password en MVP**; Google OAuth como roadmap | `email_confirmed_at` y `encrypted_password` ya están en la seed. Google requiere registrar credenciales OAuth en Google Cloud + configurar redirect URLs en el dashboard de Supabase — overhead innecesario para prototipo. |
| A3 | **JWT verificado localmente** en FastAPI, no via roundtrip a Supabase | El JWT firmado por Supabase Auth se valida con la clave compartida sin red. Es lo que recomienda Supabase para backends propios. |
| A4 | **Frontend habla con Supabase Auth directo** para signup/login; con FastAPI para todo lo demás | Reduce código en backend. FastAPI recibe el JWT como `Bearer` y lo valida. |
| A5 | **Backend usa siempre `service_role_key`** para hablar con Supabase (bypassa RLS) | Toda autorización vive en use cases (capa `application/`), no en políticas RLS. Ver [`backend.md` ADR 07](./backend.md). |
| A6 | **Promoción es vía endpoint protegido por rol `admin`** (`PATCH /usuarios/{id}/promover`). La promoción manual via SQL queda solo como **bootstrap del primer admin** | Tras agregar el rol `admin` (D9 en `bbdd.md`), el flujo de promoción se mueve a un endpoint auditable. El primer admin se crea por SQL una sola vez (no hay otro camino: nadie puede llamar el endpoint sin ser admin). Detalle en §8. |
| A7 | **Heatmap es público** (sin auth); reportes y panel municipal requieren JWT | Cualquier vecino debe poder ver ruido en su zona sin barrera. La acción de reportar/atender sí requiere identidad. |

---

## 2. Modelo de identidad

Dos tablas con relación 1:1 estricta:

```
auth.users  (Supabase Auth — schema 'auth', no tocar)
   │
   │  id (uuid) ◀──┐
   │               │ FK con ON DELETE CASCADE
   │               │
public.usuario ────┘
   ├── id           uuid          (= auth.users.id)
   ├── nombre       text
   ├── telefono     text          (opcional)
   ├── tipo         text          ('ciudadano' | 'municipalidad' | 'admin')
   ├── comuna_id    int → comuna  (NULL hasta onboarding)
   ├── activo       boolean
   └── created_at, updated_at
```

**`auth.users`** lo administra Supabase: contraseñas, email confirmado, providers OAuth, sesiones, refresh tokens. El backend lo **lee** pero nunca lo escribe directamente — todo INSERT/UPDATE a `auth.users` pasa por Supabase Auth.

**`public.usuario`** es nuestro perfil extendido. Lo poblamos automáticamente vía trigger (sección 3) cuando llega un signup. Contiene datos de negocio (rol, comuna, teléfono) que Supabase Auth no conoce ni debe conocer.

### Por qué tabla separada en lugar de `raw_user_meta_data`
Supabase permite guardar metadata en `auth.users.raw_user_meta_data` como JSONB. **No la usamos** para datos de negocio porque:
- No es relacional: no se puede hacer `JOIN ... ON usuario.comuna_id = comuna.id`.
- No es queryable eficientemente: no hay índices secundarios sobre claves JSON arbitrarias.
- Mezcla concerns: Supabase puede sobreescribirla en flujos de OAuth.

Sí leemos `raw_user_meta_data` para **extraer el nombre** al provisionar el perfil (sección 3).

---

## 3. Provisioning automático: trigger `handle_new_user`

Cada vez que llega un `INSERT` a `auth.users` (signup completado por Supabase Auth), un trigger inserta el row correspondiente en `public.usuario`. Esto garantiza la invariante **"todo usuario autenticado tiene perfil"** sin que el backend tenga que recordarlo.

```sql
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER             -- corre con permisos del owner, no del invocante
SET search_path = public     -- evita ataques de search_path
AS $$
BEGIN
  INSERT INTO public.usuario (id, nombre, tipo)
  VALUES (
    NEW.id,
    COALESCE(
      NEW.raw_user_meta_data->>'full_name',  -- Google OAuth
      NEW.raw_user_meta_data->>'name',       -- otros providers
      split_part(NEW.email, '@', 1)          -- fallback: parte local del email
    ),
    'ciudadano'                              -- todos parten como ciudadano
  );
  RETURN NEW;
END;
$$;

CREATE TRIGGER on_auth_user_created
AFTER INSERT ON auth.users
FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();
```

**Comportamiento:**
- Signup email/password con `nombre` enviado → `nombre` aparece en `raw_user_meta_data.full_name`.
- Signup sin nombre → fallback a la parte local del email.
- `comuna_id` queda **NULL** (se setea en onboarding, ver §7).
- `tipo` parte siempre como `'ciudadano'` — la promoción es manual (§5).

**Por qué `SECURITY DEFINER`:** el trigger corre con permisos del owner (postgres), no del rol que disparó el `INSERT` (Supabase Auth corre como un rol propio). Sin esto, el trigger no podría escribir en `public.usuario`.

---

## 4. Flujo de signup + login (alto nivel)

```
┌─────────────┐                                  ┌──────────────────┐
│  Frontend   │                                  │  Supabase Auth   │
│   (Vue 3)   │ ── 1. signUp(email, pwd, meta) ▶│  (REST / SDK JS) │
│             │ ◀── 2. session { jwt, user }────│                   │
└──────┬──────┘                                  └─────────┬────────┘
       │                                                   │
       │                                          3. INSERT auth.users
       │                                                   ▼
       │                                          ┌─────────────────┐
       │                                          │  trigger crea   │
       │                                          │  public.usuario │
       │                                          └─────────────────┘
       │
       │ 4. POST /api/v1/reportes
       │    Authorization: Bearer <jwt>
       ▼
┌──────────────────┐
│  FastAPI         │
│  verifica JWT    │── 5. carga usuario via service_role ──▶ public.usuario
│  ejecuta use case│
└──────────────────┘
```

**Puntos clave:**
- Pasos 1–3 viven íntegramente en Supabase. FastAPI no participa.
- A partir del paso 4, FastAPI es la única puerta a los datos.
- El JWT contiene `sub` (= `auth.users.id` = `usuario.id`) y `role` (Supabase: `authenticated`).
- El **refresh** del JWT es responsabilidad del cliente (Supabase JS SDK lo hace automáticamente).

---

## 5. Verificación de JWT en FastAPI

### Estrategia
Supabase puede firmar JWTs con dos esquemas según versión y configuración del proyecto:

- **Asimétrico (ES256 / RS256)** — default en Supabase CLI ≥ 2.x. Las claves públicas se publican en `<SUPABASE_URL>/auth/v1/.well-known/jwks.json`; el backend las descarga y cachea con `jwt.PyJWKClient` (pyjwt).
- **Simétrico (HS256)** — proyectos legacy. Verificado localmente con `SUPABASE_JWT_SECRET`.

El backend soporta ambos: inspecciona el header `alg` del token y elige el camino. En ambos casos valida `aud="authenticated"` y respeta el `exp`. **El secret HS256 sigue siendo obligatorio** porque el cliente JS del frontend puede enviar tokens HS256 si el proyecto está en modo legacy; tener ambos paths cubre los dos escenarios sin reconfigurar el cliente.

```python
# app/api/deps.py  (esquema real, ver código fuente para detalles)
from jwt import PyJWKClient
import jwt

_jwks_client: Optional[PyJWKClient] = None  # lazy
_ASYM_ALGS = {"ES256", "ES384", "RS256", "RS384"}


def _decode_jwt(token: str) -> dict:
    header = jwt.get_unverified_header(token)
    alg = header.get("alg", "")

    if alg in _ASYM_ALGS:
        key = _get_jwks_client().get_signing_key_from_jwt(token).key
        algorithms = [alg]
    elif alg == "HS256":
        key = settings.supabase_jwt_secret
        algorithms = ["HS256"]
    else:
        raise InvalidTokenError(f"Algoritmo no soportado: {alg}")

    return jwt.decode(token, key, algorithms=algorithms, audience="authenticated")


async def current_user(creds=Depends(bearer)) -> Usuario:
    if not creds:
        raise UnauthorizedError("Se requiere autenticación.")
    payload = _decode_jwt(creds.credentials)
    user = UsuarioRepository().get_by_id(payload["sub"])
    if user is None or not user.activo:
        raise UnauthorizedError("Usuario no encontrado o inactivo.")
    return user
```

### Variantes de la dependency

| Dependency | Garantiza | Uso |
|---|---|---|
| `current_user` | JWT válido + perfil existente y activo | Endpoints autenticados básicos |
| `current_user_municipal` | `current_user` + `tipo='municipalidad'` | Panel de funcionarios |
| `current_user_municipal_de_comuna(comuna_id)` | + funcionario debe pertenecer a la comuna del recurso | Acciones sobre reportes de una comuna específica |
| `current_user_admin` | `current_user` + `tipo='admin'` | Panel admin (CRUD de sensores, promoción de usuarios, listado cross-comuna) |
| `current_user_municipal_o_admin` | `current_user` + `tipo IN ('municipalidad', 'admin')` | Endpoints que ambos roles pueden invocar (ej. `GET /sensores` filtrado por comuna del funcionario, sin filtro para admin) |

Los detalles de qué excepción lanzar y cómo mapearla a HTTP están en `errores.md`.

**Nota sobre el rol admin y el filtro de comuna:** las dependencies de comuna (`current_user_municipal_de_comuna`) **no aplican a admin** — el admin es cross-comuna. Cuando un endpoint usa `current_user_municipal_o_admin` y el `usuario.tipo` resulta `admin`, se omite el filtro de comuna en el query (ver lógica concreta en cada endpoint de `api.md`).

---

## 6. Autorización (matriz de roles)

| Acción | Anónimo | `ciudadano` | `municipalidad` | `admin` |
|---|---|---|---|---|
| `GET /heatmaps` | ✅ | ✅ | ✅ | ✅ |
| `GET /health/*` | ✅ | ✅ | ✅ | ✅ |
| `GET /comunas`, `GET /tipos-estado` | ✅ | ✅ | ✅ | ✅ |
| `POST /auth/signup` (via Supabase) | ✅ | — | — | — |
| `POST /auth/login` (via Supabase) | ✅ | — | — | — |
| `POST /reportes` | ❌ | ✅ | ✅ | ✅ |
| `GET /reportes/buscar-evidencia` | ❌ | ✅ | ✅ | ✅ |
| `GET /reportes/mios` | ❌ | ✅ | ✅ | ✅ |
| `GET /reportes/{id}` | ❌ | ✅ (si dueño) | ✅ (si comuna match) | ✅ (cualquier reporte) |
| `GET /reportes/comuna/{id}` | ❌ | ❌ | ✅ (si `usuario.comuna_id = id`) | ✅ (cualquier comuna) |
| `PATCH /reportes/{id}/estado` | ❌ | ❌ | ✅ (si `reporte.comuna_id = usuario.comuna_id`) | ✅ (cualquier reporte) |
| `GET /usuarios/me`, `PATCH /usuarios/me` | ❌ | ✅ | ✅ | ✅ |
| `GET /sensores`, `GET /sensores/{id}` | ❌ | ❌ | ✅ (filtrado por su comuna) | ✅ (sin filtro) |
| `GET /sensores/resumen` | ❌ | ❌ | ✅ (su comuna) | ✅ (global o por comuna) |
| `POST /sensores` (crear) | ❌ | ❌ | ❌ | ✅ |
| `PATCH /sensores/{id}` (editar) | ❌ | ❌ | ❌ | ✅ |
| `DELETE /sensores/{id}` (soft) | ❌ | ❌ | ❌ | ✅ |
| `GET /usuarios` (listado) | ❌ | ❌ | ❌ | ✅ |
| `PATCH /usuarios/{id}/activo` | ❌ | ❌ | ❌ | ✅ |
| `PATCH /usuarios/{id}/promover` | ❌ | ❌ | ❌ | ✅ |

**Reglas operacionales:**

- **Regla de la comuna (rol `municipalidad`):** un funcionario solo actúa sobre reportes y sensores de **su propia** comuna. Validado en la capa `application/` antes de mutar.
- **Bypass de la comuna (rol `admin`):** el admin es **cross-comuna** por diseño. Cuando un endpoint usa la dependency dual (`current_user_municipal_o_admin`), si el `tipo='admin'` se omite el filtro de comuna en el query.
- **Admin no puede transicionarse a sí mismo a `ciudadano`** ni desactivarse a sí mismo. Validación en el use case para evitar dejar la plataforma sin admin (ver §8).
- **Auto-acciones bloqueadas:** un admin no se puede degradar a sí mismo via `PATCH /usuarios/{id}/promover` con `id == current_user.id` (422). Esto evita el "soft lockout" donde un admin pierde permisos por error.

---

## 7. Onboarding post-signup

El trigger deja `comuna_id` en NULL. Esto es intencional: Supabase Auth no debería conocer comunas. El frontend completa el perfil con:

```
PATCH /api/v1/usuarios/me
{
  "telefono": "+56912345678",
  "comuna_id": 13123
}
```

**Validaciones:**
- Solo el propio usuario puede modificar su perfil.
- `tipo` y `id` **no** son editables vía este endpoint.
- `comuna_id` debe existir en la tabla `comuna`.

**Casos donde `comuna_id` es NULL:**
- Usuario recién registrado, sin completar onboarding.
- Comportamiento del backend: permitir reportar (el reporte tiene su propia `comuna_id` derivable de coordenadas), pero el panel "mi comuna" no muestra nada hasta completar.

---

## 8. Promoción de usuarios

Tras D9, las promociones se hacen vía endpoint protegido `PATCH /api/v1/usuarios/{id}/promover` (`api.md` §4.20). El SQL manual queda solo como **bootstrap del primer admin** (problema del huevo y la gallina: no se puede llamar el endpoint sin ser admin).

### 8.1 Bootstrap del primer admin (una sola vez)

Manual via Supabase Dashboard → SQL Editor, con `service_role`:

```sql
UPDATE public.usuario
   SET tipo = 'admin'
 WHERE id = '<uuid-del-primer-admin>';
```

Después de esto, ese usuario puede promover a otros via endpoint.

### 8.2 Flujo de promoción posterior (vía endpoint)

```http
PATCH /api/v1/usuarios/{id}/promover
Authorization: Bearer <jwt-de-admin>
Content-Type: application/json

{
  "nuevo_tipo": "municipalidad",
  "comuna_id": 13
}
```

**Reglas validadas en el use case:**

- Solo `tipo='admin'` puede invocar (`current_user_admin`).
- `nuevo_tipo` debe ser uno de `'ciudadano' | 'municipalidad' | 'admin'`.
- Si `nuevo_tipo='municipalidad'`, **`comuna_id` es obligatorio** y debe existir en `comuna`. Sin comuna no se puede asignar a funcionario.
- Si `nuevo_tipo='admin'`, `comuna_id` puede ser `null` (admin es cross-comuna). Si viene, se acepta como afinidad informativa (no afecta autorización).
- Si `nuevo_tipo='ciudadano'`, **`comuna_id` no se modifica** (el ciudadano conserva su comuna, ya seteada en onboarding).
- **El admin no puede degradarse a sí mismo** (`id == current_user.id`) — 422 con mensaje claro.

### 8.3 Auditoría

El historial de promociones **no se persiste en una tabla dedicada** en MVP. Si se requiere, se agrega `historial_promocion (id, usuario_id, promovido_por_id, tipo_anterior, tipo_nuevo, comuna_id_anterior, comuna_id_nueva, created_at)` como roadmap. Por ahora, el log de la aplicación queda en stdout de Render con `correlation_id` para cualquier auditoría puntual.

### 8.4 Roadmap

- **Tabla `historial_promocion`** para auditoría completa cuando crezca el equipo.
- **Endpoint `DELETE /usuarios/{id}/promover`** (revertir promoción) — hoy se logra invocando `PATCH` con el tipo anterior, suficiente para MVP.

---

## 9. RLS y `service_role_key` (recap)

Detalle completo en [`bbdd.md` §6](./bbdd.md) y [`backend.md` ADR 07](./backend.md). Resumen aplicado a auth:

- Todas las tablas tienen RLS habilitado **sin políticas**.
- El cliente Supabase del backend se inicializa con `service_role_key`, que **bypassa** RLS por diseño.
- El frontend **nunca** debe instanciar el cliente JS de Supabase con la `anon_key` apuntando a estas tablas (no podrá leer nada útil de todas formas, pero la convención es: frontend → FastAPI → Supabase, no atajos).
- `service_role_key` vive en `.env` del backend. Si se filtra, **rotar inmediatamente** desde el dashboard.

**Excepción legítima:** el frontend sí instancia el cliente JS de Supabase Auth para el flujo signup/login. Ese cliente usa `anon_key`, que tiene permiso solo para operaciones de auth, no para leer tablas.

---

## 10. Variables de entorno requeridas

```bash
# .env
SUPABASE_URL=https://<project>.supabase.co
SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1...        # usado por frontend, NO por backend
SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOiJIUzI1... # secreto, solo backend
SUPABASE_JWT_SECRET=<32+ caracteres>          # para verificar JWTs localmente
```

Cargadas via `pydantic-settings` en `app/core/config.py`.

---

## 11. Manejo de errores (resumen)

Detalle en `errores.md`. Mapeos clave:

| Situación | HTTP | Excepción de dominio |
|---|---|---|
| JWT ausente | 401 | (FastAPI) |
| JWT inválido / expirado | 401 | `InvalidTokenError` |
| Usuario JWT-válido pero perfil ausente o `activo=false` | 401 | `UserNotFoundError` |
| Rol insuficiente (ciudadano intenta acción municipal) | 403 | `UnauthorizedError` |
| Funcionario actúa sobre comuna ajena | 403 | `UnauthorizedError` |
| Recurso inexistente | 404 | `NotFoundError` |

---

## 12. Roadmap

- **Google OAuth** se depreca. No se ocupará. Requiere: registrar credenciales en Google Cloud Console, configurar redirect URLs en Supabase dashboard, agregar botón "Continuar con Google" en frontend. Cero cambios en backend.
- **Magic links** para password-less login.
- **Rol `admin`** explícito + endpoint de promoción auditado, cuando la operación manual ya no escale.
- **Bloqueo por intentos fallidos**: Supabase Auth ya provee rate limiting básico; revisar si alcanza.
- **Sesiones revocables**: si `usuario.activo = false`, hoy bloqueamos en backend; revisar invalidación del JWT en Supabase Auth.
