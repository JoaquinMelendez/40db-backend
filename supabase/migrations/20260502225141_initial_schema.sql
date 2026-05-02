-- ============================================================================
-- Sistema de Reportes Ciudadanos + IoT
-- Migración inicial: esquema, triggers, RLS, seed
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. Catálogos
-- ----------------------------------------------------------------------------

CREATE TABLE comuna (
  id          int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  nombre      text NOT NULL UNIQUE,
  region      text,
  codigo      text UNIQUE
);

CREATE TABLE tipo_estado (
  id          int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  nombre      text NOT NULL UNIQUE,
  descripcion text,
  orden       int NOT NULL DEFAULT 0
);

-- ----------------------------------------------------------------------------
-- 2. Usuario (perfil extendido sobre auth.users)
-- ----------------------------------------------------------------------------

CREATE TABLE usuario (
  id          uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  nombre      text NOT NULL,
  telefono    text,
  tipo        text NOT NULL DEFAULT 'ciudadano'
              CHECK (tipo IN ('ciudadano', 'municipalidad')),
  comuna_id   int REFERENCES comuna(id),
  activo      boolean NOT NULL DEFAULT true,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_usuario_tipo ON usuario(tipo);

-- ----------------------------------------------------------------------------
-- 3. Reporte
-- ----------------------------------------------------------------------------

CREATE TABLE reporte (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  usuario_id      uuid NOT NULL REFERENCES usuario(id),
  atendido_por_id uuid REFERENCES usuario(id),
  comuna_id       int NOT NULL REFERENCES comuna(id),
  titulo          text NOT NULL,
  descripcion     text NOT NULL,
  latitud         numeric(10, 8) NOT NULL,
  longitud        numeric(11, 8) NOT NULL,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_reporte_usuario ON reporte(usuario_id);
CREATE INDEX idx_reporte_comuna ON reporte(comuna_id);
CREATE INDEX idx_reporte_atendido_por ON reporte(atendido_por_id)
  WHERE atendido_por_id IS NOT NULL;

-- ----------------------------------------------------------------------------
-- 4. HistorialEstado (último registro = estado actual)
-- ----------------------------------------------------------------------------

CREATE TABLE historial_estado (
  id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  reporte_id      uuid NOT NULL REFERENCES reporte(id) ON DELETE CASCADE,
  tipo_estado_id  int NOT NULL REFERENCES tipo_estado(id),
  usuario_id      uuid REFERENCES usuario(id),
  comentario      text,
  created_at      timestamptz NOT NULL DEFAULT now()
);

-- CRÍTICO: este índice hace barata la consulta del estado actual
CREATE INDEX idx_historial_reporte_created
  ON historial_estado(reporte_id, created_at DESC);

-- ----------------------------------------------------------------------------
-- 5. Sensor + Lectura
-- ----------------------------------------------------------------------------

CREATE TABLE sensor (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  comuna_id   int NOT NULL REFERENCES comuna(id),
  nombre      text NOT NULL UNIQUE,
  latitud     numeric(10, 8) NOT NULL,
  longitud    numeric(11, 8) NOT NULL,
  activo      boolean NOT NULL DEFAULT true,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_sensor_comuna ON sensor(comuna_id);

CREATE TABLE lectura (
  id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  sensor_id           uuid NOT NULL REFERENCES sensor(id) ON DELETE CASCADE,
  nivel_db            numeric(5, 2) NOT NULL,
  timestamp_medicion  timestamptz NOT NULL,
  created_at          timestamptz NOT NULL DEFAULT now()
);

-- CRÍTICOS: heatmap (filtro temporal) y matching IoT por sensor+tiempo
CREATE INDEX idx_lectura_timestamp ON lectura(timestamp_medicion);
CREATE INDEX idx_lectura_sensor_timestamp
  ON lectura(sensor_id, timestamp_medicion);

-- ----------------------------------------------------------------------------
-- 6. ValidacionIoT (asociativa N:M)
-- ----------------------------------------------------------------------------

CREATE TABLE validacion_iot (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  reporte_id  uuid NOT NULL REFERENCES reporte(id) ON DELETE CASCADE,
  lectura_id  bigint NOT NULL REFERENCES lectura(id) ON DELETE CASCADE,
  score       numeric(3, 2) NOT NULL CHECK (score >= 0 AND score <= 1),
  metodo      text NOT NULL DEFAULT 'automatico'
              CHECK (metodo IN ('automatico', 'manual')),
  usuario_id  uuid REFERENCES usuario(id),
  created_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (reporte_id, lectura_id)
);

CREATE INDEX idx_validacion_reporte ON validacion_iot(reporte_id);
CREATE INDEX idx_validacion_lectura ON validacion_iot(lectura_id);

-- ----------------------------------------------------------------------------
-- 7. Triggers
-- ----------------------------------------------------------------------------

-- 7.1 Auto-crear perfil cuando llega un nuevo auth.users (Google OAuth)
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  INSERT INTO public.usuario (id, nombre, tipo)
  VALUES (
    NEW.id,
    COALESCE(
      NEW.raw_user_meta_data->>'full_name',
      NEW.raw_user_meta_data->>'name',
      split_part(NEW.email, '@', 1)
    ),
    'ciudadano'
  );
  RETURN NEW;
END;
$$;

CREATE TRIGGER on_auth_user_created
AFTER INSERT ON auth.users
FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- 7.2 Crear primer historial_estado ('En espera') al insertar reporte
CREATE OR REPLACE FUNCTION public.set_initial_estado()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  v_estado_id int;
BEGIN
  SELECT id INTO v_estado_id
  FROM public.tipo_estado
  WHERE nombre = 'En espera'
  LIMIT 1;

  IF v_estado_id IS NULL THEN
    RAISE EXCEPTION 'tipo_estado "En espera" no existe en el catalogo';
  END IF;

  INSERT INTO public.historial_estado (reporte_id, tipo_estado_id, usuario_id)
  VALUES (NEW.id, v_estado_id, NEW.usuario_id);

  RETURN NEW;
END;
$$;

CREATE TRIGGER on_reporte_created
AFTER INSERT ON public.reporte
FOR EACH ROW EXECUTE FUNCTION public.set_initial_estado();

-- 7.3 Mantener updated_at automático
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

CREATE TRIGGER usuario_set_updated_at BEFORE UPDATE ON usuario
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE TRIGGER reporte_set_updated_at BEFORE UPDATE ON reporte
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE TRIGGER sensor_set_updated_at BEFORE UPDATE ON sensor
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- ----------------------------------------------------------------------------
-- 8. Row Level Security
--    Habilitado sin políticas: anon/authenticated NO pueden leer/escribir.
--    El backend usa service_role_key, que bypassa RLS por diseño.
-- ----------------------------------------------------------------------------

ALTER TABLE comuna           ENABLE ROW LEVEL SECURITY;
ALTER TABLE tipo_estado      ENABLE ROW LEVEL SECURITY;
ALTER TABLE usuario          ENABLE ROW LEVEL SECURITY;
ALTER TABLE reporte          ENABLE ROW LEVEL SECURITY;
ALTER TABLE historial_estado ENABLE ROW LEVEL SECURITY;
ALTER TABLE sensor           ENABLE ROW LEVEL SECURITY;
ALTER TABLE lectura          ENABLE ROW LEVEL SECURITY;
ALTER TABLE validacion_iot   ENABLE ROW LEVEL SECURITY;

-- ----------------------------------------------------------------------------
-- 9. Seed inicial
-- ----------------------------------------------------------------------------

INSERT INTO tipo_estado (nombre, descripcion, orden) VALUES
  ('En espera',   'Reporte creado, sin asignar',      1),
  ('En atencion', 'Funcionario asignado trabajando',  2),
  ('Atendido',    'Reporte resuelto',                 3),
  ('Descartado',  'Reporte invalido o duplicado',     4);


-- Realizar insert Mock