from app.infrastructure.db.lectura_repo import LecturaRepository


def registrar_lectura(sensor_id: str, nivel_db: float, timestamp_medicion: str) -> None:
    repo = LecturaRepository()
    repo.insert(sensor_id=sensor_id, nivel_db=nivel_db, timestamp_medicion=timestamp_medicion)
