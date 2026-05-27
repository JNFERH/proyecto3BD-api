from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
from datetime import datetime
from typing import Optional
import os

app = FastAPI()

# CORS - Permitir peticiones desde APEX
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

# Conexión a MongoDB
# Para desarrollo local:

client = MongoClient(os.environ["MONGO_URI"])
db = client["proyecto3"]  

# ============================================================================
# ENDPOINTS BÁSICOS
# ============================================================================

@app.get("/")
def inicio():
    return {"estado": "API Dann-Alpes funcionando correctamente"}

@app.get("/health")
def health_check():
    """Verifica que la conexión a MongoDB esté activa"""
    try:
        client.admin.command('ping')
        return {"status": "healthy", "database": "dann_alpes_resenas"}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


# ============================================================================
# RF1 - CREAR RESEÑA
# ============================================================================

@app.post('/hoteles/{hotel_id}/resenas')
def crear_resena(hotel_id: str, datos: dict):
    """
    Crear una nueva reseña para un hotel.
    
    Validaciones:
    - Reserva debe estar completada (verificar en Oracle)
    - No debe haber reseña previa para esa reserva
    
    Datos esperados:
    {
        "reserva_id": "RES001",
        "cliente_id": "CLI001",
        "calificacion": 4,
        "texto": "Excelente experiencia en el hotel..."
    }
    """
    try:
        # Validar que no existe reseña previa para esta reserva
        resena_existente = db['resenas'].find_one({
            'reserva_id': datos['reserva_id']
        })
        
        if resena_existente:
            raise HTTPException(
                status_code=400, 
                detail="Ya existe una reseña para esta reserva"
            )
        
        # Construir documento de reseña
        nueva_resena = {
            'reserva_id': datos['reserva_id'],
            'hotel_id': hotel_id,
            'cliente_id': datos['cliente_id'],
            'calificacion': int(datos['calificacion']),
            'texto': datos['texto'],
            'fecha_creacion': datetime.now(),
            'estado': 'publicada',
            'destacada': False,
            'votos_utiles': 0
        }
        
        resultado = db['resenas'].insert_one(nueva_resena)
        
        return {
            'mensaje': 'Reseña creada exitosamente',
            'resena_id': str(resultado.inserted_id)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# RF2 - EDITAR RESEÑA
# ============================================================================

@app.put('/resenas/{reserva_id}')
def editar_resena(reserva_id: str, datos: dict):
    """
    Editar una reseña existente (calificación y/o texto).
    
    Datos esperados:
    {
        "calificacion": 5,
        "texto": "Texto actualizado..."
    }
    """
    try:
        actualizar = {}
        if 'calificacion' in datos:
            actualizar['calificacion'] = int(datos['calificacion'])
        if 'texto' in datos:
            actualizar['texto'] = datos['texto']
        
        resultado = db['resenas'].update_one(
            {'reserva_id': reserva_id},
            {'$set': actualizar}
        )
        
        if resultado.matched_count == 0:
            raise HTTPException(status_code=404, detail="Reseña no encontrada")
        
        return {'mensaje': 'Reseña actualizada exitosamente'}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# RF3 - ELIMINAR RESEÑA (Borrado lógico)
# ============================================================================

@app.delete('/resenas/{reserva_id}')
def eliminar_resena(reserva_id: str):
    """
    Eliminar una reseña (cambiar estado a 'eliminada').
    """
    try:
        resultado = db['resenas'].update_one(
            {'reserva_id': reserva_id},
            {'$set': {'estado': 'eliminada'}}
        )
        
        if resultado.matched_count == 0:
            raise HTTPException(status_code=404, detail="Reseña no encontrada")
        
        return {'mensaje': 'Reseña eliminada exitosamente'}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# RF4 - CONSULTAR RESEÑAS DE UN HOTEL (CON PAGINACIÓN)
# ============================================================================

@app.get('/hoteles/{hotel_id}/resenas')
def get_resenas_hotel(
    hotel_id: str,
    ordenar_por: str = 'fecha',  # 'fecha' o 'utilidad'
    pagina: int = 1,
    por_pagina: int = 10
):
    """
    Obtener reseñas publicadas de un hotel con paginación y ordenamiento.
    
    Parámetros:
    - ordenar_por: 'fecha' (desc) o 'utilidad' (desc)
    - pagina: número de página (comienza en 1)
    - por_pagina: cantidad de reseñas por página
    """
    try:
        # Definir ordenamiento
        ordenamiento = [('fecha_creacion', -1)]
        if ordenar_por == 'utilidad':
            ordenamiento = [('votos_utiles', -1)]
        
        # Calcular skip
        skip = (pagina - 1) * por_pagina
        
        # Consulta
        resenas = list(db['resenas'].find(
            {
                'hotel_id': hotel_id,
                'estado': 'publicada'
            },
            {
                '_id': 0,
                'reserva_id': 1,
                'cliente_id': 1,
                'calificacion': 1,
                'texto': 1,
                'fecha_creacion': 1,
                'votos_utiles': 1,
                'respuesta_admin': 1
            }
        ).sort(ordenamiento).skip(skip).limit(por_pagina))
        
        # Contar total
        total = db['resenas'].count_documents({
            'hotel_id': hotel_id,
            'estado': 'publicada'
        })
        
        return {
            'resenas': resenas,
            'pagina': pagina,
            'por_pagina': por_pagina,
            'total': total,
            'total_paginas': (total + por_pagina - 1) // por_pagina
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# RF5 - MARCAR RESEÑA COMO ÚTIL
# ============================================================================

@app.post('/resenas/{reserva_id}/votos')
def votar_resena(reserva_id: str, datos: dict):
    """
    Registrar un voto de utilidad para una reseña.
    
    Datos esperados:
    {
        "usuario_id": "USR001"
    }
    
    Validación: Un usuario solo puede votar una vez por reseña.
    """
    try:
        usuario_id = datos['usuario_id']
        
        # Verificar que el usuario no haya votado antes
        voto_existente = db['votos'].find_one({
            'resena_id': reserva_id,
            'usuario_id': usuario_id
        })
        
        if voto_existente:
            raise HTTPException(
                status_code=400,
                detail="Este usuario ya votó esta reseña"
            )
        
        # Registrar voto en colección 'votos'
        db['votos'].insert_one({
            'resena_id': reserva_id,
            'usuario_id': usuario_id,
            'fecha': datetime.now()
        })
        
        # Incrementar contador en reseña
        db['resenas'].update_one(
            {'reserva_id': reserva_id},
            {'$inc': {'votos_utiles': 1}}
        )
        
        return {'mensaje': 'Voto registrado exitosamente'}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# RF6 - CONSULTAR HISTORIAL DE RESEÑAS PROPIAS
# ============================================================================

@app.get('/clientes/{cliente_id}/mis-resenas')
def get_mis_resenas(
    cliente_id: str,
    ordenar_por: str = 'fecha',  # 'fecha', 'hotel', 'calificacion'
):
    """
    Obtener todas las reseñas del cliente autenticado.
    
    Incluye:
    - Estado actual (publicada, eliminada)
    - Calificación dada
    - Si recibió respuesta del hotel
    - Cantidad de usuarios que la marcaron como útil
    """
    try:
        # Definir ordenamiento
        ordenamientos = {
            'fecha': [('fecha_creacion', -1)],
            'hotel': [('hotel_id', 1)],
            'calificacion': [('calificacion', -1)]
        }
        
        ordenamiento = ordenamientos.get(ordenar_por, ordenamientos['fecha'])
        
        # Consulta
        resenas = list(db['resenas'].find(
            {'cliente_id': cliente_id},
            {
                '_id': 0,
                'reserva_id': 1,
                'hotel_id': 1,
                'calificacion': 1,
                'texto': 1,
                'fecha_creacion': 1,
                'estado': 1,
                'votos_utiles': 1,
                'respuesta_admin': 1
            }
        ).sort(ordenamiento))
        
        # Procesamiento: agregar campo "tiene_respuesta"
        for resena in resenas:
            resena['tiene_respuesta'] = 'respuesta_admin' in resena and resena['respuesta_admin'] is not None
        
        return {'resenas': resenas}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# RF7 - RESPONDER RESEÑA (ADMIN)
# ============================================================================

@app.post('/resenas/{reserva_id}/respuesta-admin')
def responder_resena(reserva_id: str, datos: dict):
    """
    Agregar o editar la respuesta oficial del administrador.
    
    Datos esperados:
    {
        "admin_id": "ADM001",
        "texto": "Agradecemos tu comentario..."
    }
    """
    try:
        respuesta_admin = {
            'admin_id': datos['admin_id'],
            'texto': datos['texto'],
            'fecha': datetime.now()
        }
        
        resultado = db['resenas'].update_one(
            {'reserva_id': reserva_id},
            {'$set': {'respuesta_admin': respuesta_admin}}
        )
        
        if resultado.matched_count == 0:
            raise HTTPException(status_code=404, detail="Reseña no encontrada")
        
        return {'mensaje': 'Respuesta registrada exitosamente'}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# RF8 - ELIMINAR RESEÑA (ADMIN - por violación de políticas)
# ============================================================================

@app.delete('/admin/resenas/{reserva_id}')
def eliminar_resena_admin(reserva_id: str, datos: dict):
    """
    Eliminar reseña que viola políticas (solo admin).
    
    Datos esperados:
    {
        "razon": "Contenido ofensivo"
    }
    """
    try:
        resultado = db['resenas'].update_one(
            {'reserva_id': reserva_id},
            {
                '$set': {
                    'estado': 'eliminada',
                    'razon_eliminacion_admin': datos.get('razon', 'Violación de políticas')
                }
            }
        )
        
        if resultado.matched_count == 0:
            raise HTTPException(status_code=404, detail="Reseña no encontrada")
        
        return {'mensaje': 'Reseña eliminada por administrador'}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# RF9 - DESTACAR RESEÑA (ADMIN)
# ============================================================================

@app.put('/admin/resenas/{reserva_id}/destacar')
def destacar_resena(reserva_id: str, datos: dict):
    """
    Marcar una reseña como destacada.
    
    Validación: Solo puede haber una reseña destacada por hotel.
    
    Datos esperados:
    {
        "hotel_id": "HTL001",
        "destacada": true
    }
    """
    try:
        hotel_id = datos['hotel_id']
        destacada = datos.get('destacada', True)
        
        if destacada:
            # Si se marca como destacada, desmarcar otras del mismo hotel
            db['resenas'].update_many(
                {
                    'hotel_id': hotel_id,
                    'reserva_id': {'$ne': reserva_id}
                },
                {'$set': {'destacada': False}}
            )
        
        # Actualizar la reseña actual
        resultado = db['resenas'].update_one(
            {'reserva_id': reserva_id},
            {'$set': {'destacada': destacada}}
        )
        
        if resultado.matched_count == 0:
            raise HTTPException(status_code=404, detail="Reseña no encontrada")
        
        return {'mensaje': f"Reseña {'destacada' if destacada else 'desdestacada'} exitosamente"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# RFC1 - TOP 10 HOTELES POR CALIFICACIÓN
# ============================================================================

@app.get('/reportes/top-hoteles')
def rfc1_top_hoteles(
    fecha_inicio: str,  # Formato: "2025-01-01"
    fecha_fin: str      # Formato: "2025-12-31"
):
    """
    Consultar los 10 hoteles con mejor calificación promedio en un período.
    
    Parámetros:
    - fecha_inicio: YYYY-MM-DD
    - fecha_fin: YYYY-MM-DD
    """
    try:
        fecha_inicio_dt = datetime.fromisoformat(fecha_inicio)
        fecha_fin_dt = datetime.fromisoformat(fecha_fin)
        
        pipeline = [
            {
                '$match': {
                    'estado': 'publicada',
                    'fecha_creacion': {'$gte': fecha_inicio_dt, '$lte': fecha_fin_dt}
                }
            },
            {
                '$group': {
                    '_id': '$hotel_id',
                    'calificacion_promedio': {'$avg': '$calificacion'},
                    'total_resenas': {'$sum': 1}
                }
            },
            {'$sort': {'calificacion_promedio': -1}},
            {'$limit': 10},
            {
                '$project': {
                    '_id': 0,
                    'hotel_id': '$_id',
                    'nombre_hotel': '$nombre_hotel',
                    'ciudad': '$ciudad',
                    'calificacion_promedio': {'$round': ['$calificacion_promedio', 2]},
                    'total_resenas': 1
                }
            }
        ]
        
        resultado = list(db['resenas'].aggregate(pipeline))
        return {'hoteles': resultado}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# RFC2 - EVOLUCIÓN DE REPUTACIÓN MENSUAL
# ============================================================================

@app.get('/reportes/evolucion-reputacion/{hotel_id}')
def rfc2_evolucion_reputacion(hotel_id: str, anio: int = 2025):
    """
    Mostrar evolución de la calificación promedio mensual de un hotel en un año.
    
    Parámetros:
    - hotel_id: ID del hotel
    - anio: Año a analizar (default: 2025)
    """
    try:
        pipeline = [
            {
                '$match': {
                    'hotel_id': hotel_id,
                    'estado': 'publicada',
                    '$expr': {'$eq': [{'$year': '$fecha_creacion'}, anio]}
                }
            },
            {
                '$group': {
                    '_id': {'mes': {'$month': '$fecha_creacion'}},
                    'calificacion_promedio': {'$avg': '$calificacion'},
                    'total_resenas': {'$sum': 1}
                }
            },
            {'$sort': {'_id.mes': 1}},
            {
                '$project': {
                    '_id': 0,
                    'mes': '$_id.mes',
                    'calificacion_promedio': {'$round': ['$calificacion_promedio', 2]},
                    'total_resenas': 1
                }
            }
        ]
        
        resultado = list(db['resenas'].aggregate(pipeline))
        return {'hotel_id': hotel_id, 'anio': anio, 'datos': resultado}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# RFC3 - PERFIL COMPARATIVO POR CIUDAD
# ============================================================================

@app.get('/reportes/perfil-ciudad/{ciudad}')
def rfc3_perfil_ciudad(ciudad: str):
    """
    Perfil comparativo de hoteles en una ciudad.
    
    Incluye:
    - Calificación promedio general
    - Total de reseñas
    - % de reseñas con respuesta
    - % de reseñas destacadas
    - Identifica hoteles bajo promedio
    """
    try:
        pipeline = [
            {
                '$match': {
                    'ciudad_hotel': ciudad,
                    'estado': 'publicada'
                }
            },
            {
                '$group': {
                    '_id': '$hotel_id',
                    'calificacion_promedio': {'$avg': '$calificacion'},
                    'total_resenas': {'$sum': 1},
                    'con_respuesta': {
                        '$sum': {'$cond': [{'$ifNull': ['$respuesta_admin', False]}, 1, 0]}
                    },
                    'destacadas': {
                        '$sum': {'$cond': [{'$eq': ['$destacada', True]}, 1, 0]}
                    }
                }
            },
            {
                '$addFields': {
                    'pct_con_respuesta': {
                        '$round': [
                            {'$multiply': [{'$divide': ['$con_respuesta', '$total_resenas']}, 100]}, 1
                        ]
                    },
                    'pct_destacadas': {
                        '$round': [
                            {'$multiply': [{'$divide': ['$destacadas', '$total_resenas']}, 100]}, 1
                        ]
                    }
                }
            },
            {'$sort': {'calificacion_promedio': -1}},
            {
                '$group': {
                    '_id': None,
                    'promedio_ciudad': {'$avg': '$calificacion_promedio'},
                    'hoteles': {'$push': '$$ROOT'}
                }
            },
            {'$unwind': '$hoteles'},
            {
                '$addFields': {
                    'hoteles.bajo_promedio_ciudad': {
                        '$lt': ['$hoteles.calificacion_promedio', '$promedio_ciudad']
                    },
                    'hoteles.promedio_ciudad': {'$round': ['$promedio_ciudad', 2]}
                }
            },
            {'$replaceRoot': {'newRoot': '$hoteles'}},
            {
                '$project': {
                    '_id': 0,
                    'hotel_id': '$_id',
                    'calificacion_promedio': {'$round': ['$calificacion_promedio', 2]},
                    'total_resenas': 1,
                    'pct_con_respuesta': 1,
                    'pct_destacadas': 1,
                    'promedio_ciudad': 1,
                    'bajo_promedio_ciudad': 1
                }
            }
        ]
        
        resultado = list(db['resenas'].aggregate(pipeline))
        
        # Obtener promedio general
        promedio_general = db['resenas'].aggregate([
            {
                '$match': {
                    'ciudad_hotel': ciudad,
                    'estado': 'publicada'
                }
            },
            {
                '$group': {
                    '_id': None,
                    'promedio': {'$avg': '$calificacion'},
                    'total_resenas': {'$sum': 1}
                }
            }
        ])
        
        stats = list(promedio_general)[0] if list(promedio_general) else {}
        
        return {
            'ciudad': ciudad,
            'promedio_general': round(stats.get('promedio', 0), 2),
            'total_resenas_ciudad': stats.get('total_resenas', 0),
            'hoteles': resultado
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ENDPOINT ADICIONAL: OBTENER RESEÑA POR ID
# ============================================================================

@app.get('/resenas/{reserva_id}')
def get_resena(reserva_id: str):
    """
    Obtener una reseña específica por reserva_id.
    """
    try:
        resena = db['resenas'].find_one(
            {'reserva_id': reserva_id},
            {'_id': 0}
        )
        
        if not resena:
            raise HTTPException(status_code=404, detail="Reseña no encontrada")
        
        return resena
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))