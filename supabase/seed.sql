-- ============================================================================
-- 40dB — Seed de desarrollo
-- Ejecutado por: supabase db reset
-- ============================================================================

-- Catálogo de estados (obligatorio para el trigger set_initial_estado)
INSERT INTO tipo_estado (nombre, descripcion, orden) VALUES
  ('En espera',   'Reporte creado, sin asignar',     1),
  ('En atencion', 'Funcionario asignado trabajando', 2),
  ('Atendido',    'Reporte resuelto',                3),
  ('Descartado',  'Reporte invalido o duplicado',    4);

-- Comunas de prueba
INSERT INTO comuna (nombre, region, codigo) VALUES
  ('Santiago',    'Metropolitana', '13101'),
  ('Providencia', 'Metropolitana', '13123'),
  ('Las Condes',  'Metropolitana', '13114');

-- Sensores mock (ubición referencial en el centro de cada comuna)
-- Nota: la columna `ubicacion` geography se genera automáticamente desde lat/lng
INSERT INTO sensor (comuna_id, nombre, latitud, longitud) VALUES
  ((SELECT id FROM comuna WHERE codigo = '13101'), 'Plaza de Armas - Centro',  -33.43800, -70.65010),
  ((SELECT id FROM comuna WHERE codigo = '13123'), 'Plaza Italia - Norte',      -33.43720, -70.64830),
  ((SELECT id FROM comuna WHERE codigo = '13114'), 'Apoquindo - Las Condes',    -33.41450, -70.59780);

-- Lecturas mock variadas (algunas sobre umbral 65 dB, otras debajo)
-- Se insertan con timestamps recientes para que el matching IoT funcione en tests
INSERT INTO lectura (sensor_id, nivel_db, timestamp_medicion) VALUES
  ((SELECT id FROM sensor WHERE nombre = 'Plaza de Armas - Centro'),  72.5,  now() - interval '2 minutes'),
  ((SELECT id FROM sensor WHERE nombre = 'Plaza de Armas - Centro'),  58.3,  now() - interval '5 minutes'),
  ((SELECT id FROM sensor WHERE nombre = 'Plaza Italia - Norte'),      78.1,  now() - interval '1 minute'),
  ((SELECT id FROM sensor WHERE nombre = 'Plaza Italia - Norte'),      63.0,  now() - interval '8 minutes'),
  ((SELECT id FROM sensor WHERE nombre = 'Apoquindo - Las Condes'),    55.2,  now() - interval '3 minutes');

-- Nota: usuarios y reportes mock requieren filas en auth.users primero.
-- Se crean manualmente via Supabase Auth en el entorno local o se agregan
-- con supabase-specific helpers. No se incluyen aquí para evitar dependencias
-- de auth en el seed básico.
