-- ============================================================================
-- Seed para desarrollo local
-- Se ejecuta automáticamente con: supabase db reset
-- Ubicación esperada: supabase/seed.sql
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. Comunas (catálogo de prueba — en prod usar lista oficial)
-- ----------------------------------------------------------------------------
INSERT INTO comuna (nombre, region, codigo) VALUES
  ('Santiago',    'Metropolitana', '13101'),
  ('Providencia', 'Metropolitana', '13123'),
  ('Las Condes',  'Metropolitana', '13114');

-- ----------------------------------------------------------------------------
-- 2. Usuarios de prueba
--    Insertamos en auth.users; el trigger handle_new_user crea el perfil.
--    Luego hacemos UPDATE para asignar comuna y, en un caso, tipo municipal.
-- ----------------------------------------------------------------------------
INSERT INTO auth.users (
  id, instance_id, aud, role, email, encrypted_password,
  email_confirmed_at, raw_user_meta_data, created_at, updated_at
) VALUES
  ('11111111-1111-1111-1111-111111111111',
   '00000000-0000-0000-0000-000000000000',
   'authenticated', 'authenticated',
   'ana@test.cl', crypt('password123', gen_salt('bf')),
   now(), '{"full_name": "Ana Pérez"}'::jsonb, now(), now()),
  ('22222222-2222-2222-2222-222222222222',
   '00000000-0000-0000-0000-000000000000',
   'authenticated', 'authenticated',
   'carlos@test.cl', crypt('password123', gen_salt('bf')),
   now(), '{"full_name": "Carlos Ruiz"}'::jsonb, now(), now()),
  ('33333333-3333-3333-3333-333333333333',
   '00000000-0000-0000-0000-000000000000',
   'authenticated', 'authenticated',
   'funcionario@providencia.cl', crypt('password123', gen_salt('bf')),
   now(), '{"full_name": "María Soto"}'::jsonb, now(), now());

-- Asignar comunas y promover al funcionario municipal
UPDATE usuario
   SET comuna_id = (SELECT id FROM comuna WHERE nombre = 'Providencia')
 WHERE id = '11111111-1111-1111-1111-111111111111';

UPDATE usuario
   SET comuna_id = (SELECT id FROM comuna WHERE nombre = 'Las Condes')
 WHERE id = '22222222-2222-2222-2222-222222222222';

UPDATE usuario
   SET tipo      = 'municipalidad',
       comuna_id = (SELECT id FROM comuna WHERE nombre = 'Providencia')
 WHERE id = '33333333-3333-3333-3333-333333333333';

-- ----------------------------------------------------------------------------
-- 3. Sensores
-- ----------------------------------------------------------------------------
INSERT INTO sensor (id, comuna_id, nombre, latitud, longitud) VALUES
  ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1',
   (SELECT id FROM comuna WHERE nombre = 'Providencia'),
   'SNS-Pedro de Valdivia 01', -33.42950000, -70.61500000),
  ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa2',
   (SELECT id FROM comuna WHERE nombre = 'Providencia'),
   'SNS-Av. Providencia 02',   -33.42100000, -70.60800000),
  ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa3',
   (SELECT id FROM comuna WHERE nombre = 'Las Condes'),
   'SNS-Apoquindo 01',         -33.40800000, -70.56000000);

-- ----------------------------------------------------------------------------
-- 4. Lecturas (mezcla niveles altos y bajos para probar matching IoT)
-- ----------------------------------------------------------------------------
INSERT INTO lectura (sensor_id, nivel_db, timestamp_medicion) VALUES
  -- Sensor 1: ruido alto coincidente con reporte
  ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1', 78.50, now() - interval '2 hours'),
  ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1', 82.30, now() - interval '1 hour'),
  -- Sensor 2: ruido bajo (debería dar score bajo en validación)
  ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa2', 55.20, now() - interval '45 minutes'),
  ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa2', 58.10, now() - interval '30 minutes'),
  -- Sensor 3: ruido medio
  ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa3', 70.10, now() - interval '15 minutes');

-- ----------------------------------------------------------------------------
-- 5. Reportes (el trigger set_initial_estado crea el 'En espera' solo)
-- ----------------------------------------------------------------------------
INSERT INTO reporte (id, usuario_id, comuna_id, titulo, descripcion, latitud, longitud) VALUES
  ('dddddddd-dddd-dddd-dddd-ddddddddddd1',
   '11111111-1111-1111-1111-111111111111',
   (SELECT id FROM comuna WHERE nombre = 'Providencia'),
   'Ruido excesivo en obra de construcción',
   'Llevan toda la semana partiendo a las 6 AM con martillo neumático.',
   -33.42950000, -70.61500000),
  ('dddddddd-dddd-dddd-dddd-ddddddddddd2',
   '22222222-2222-2222-2222-222222222222',
   (SELECT id FROM comuna WHERE nombre = 'Providencia'),
   'Bocinazos constantes en hora punta',
   'Esquina con taco perpetuo, los autos no paran de tocar bocina.',
   -33.42100000, -70.60800000),
  ('dddddddd-dddd-dddd-dddd-ddddddddddd3',
   '11111111-1111-1111-1111-111111111111',
   (SELECT id FROM comuna WHERE nombre = 'Las Condes'),
   'Discotheque con música hasta las 4 AM',
   'Local nocturno funcionando fuera de horario permitido.',
   -33.40800000, -70.56000000);

-- Avanzar el primer reporte a 'En atencion' (segundo registro de historial)
INSERT INTO historial_estado (reporte_id, tipo_estado_id, usuario_id, comentario) VALUES
  ('dddddddd-dddd-dddd-dddd-ddddddddddd1',
   (SELECT id FROM tipo_estado WHERE nombre = 'En atencion'),
   '33333333-3333-3333-3333-333333333333',
   'Inspección municipal asignada para mañana');

UPDATE reporte
   SET atendido_por_id = '33333333-3333-3333-3333-333333333333'
 WHERE id = 'dddddddd-dddd-dddd-dddd-ddddddddddd1';

-- ----------------------------------------------------------------------------
-- 6. Validaciones IoT (cruce reporte ↔ lectura cercana en tiempo+espacio)
-- ----------------------------------------------------------------------------
INSERT INTO validacion_iot (reporte_id, lectura_id, score, metodo) VALUES
  -- Reporte 1 ↔ lectura más reciente del sensor 1: nivel alto → score alto
  ('dddddddd-dddd-dddd-dddd-ddddddddddd1',
   (SELECT id FROM lectura
      WHERE sensor_id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1'
      ORDER BY timestamp_medicion DESC LIMIT 1),
   0.92, 'automatico'),
  -- Reporte 2 ↔ lectura del sensor 2: nivel bajo → score bajo
  ('dddddddd-dddd-dddd-dddd-ddddddddddd2',
   (SELECT id FROM lectura
      WHERE sensor_id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa2'
      ORDER BY timestamp_medicion DESC LIMIT 1),
   0.38, 'automatico');
-- Reporte 3 queda sin validación a propósito (caso "sin sensor cercano")