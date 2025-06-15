from flask import Flask, render_template, request, jsonify, send_from_directory
import os
import requests
from math import isclose, atan2, degrees

app = Flask(__name__)

# --- Configuración Centralizada ---
# Puedes ajustar estos valores para controlar la flexibilidad de la ruta Manhattan.
# Prueba diferentes valores para ver cómo afecta el comportamiento.
class Config:
    OSRM_BASE_URL = "http://router.project-osrm.org/route/v1/"
    OSRM_TIMEOUT_SECONDS = 15 # Aumentado ligeramente para dar más tiempo a OSRM
    
    # Tolerancia para la tendencia principal de los segmentos de la 'L' de Manhattan (Origen-Intermedio, Intermedio-Destino).
    # Un valor más alto permite que la 'L' sea menos "perfecta" geométricamente.
    # Recomendado: 10 a 30 grados.
    TOLERANCIA_MANHATTAN_TENDENCIA_PRINCIPAL_GRADOS = 25 # Ajustado para mayor flexibilidad en la forma general
    
    # Este es el valor MÁS IMPORTANTE a ajustar para que se encuentre la ruta Manhattan.
    # Si lo aumentas, permitirás que los segmentos de calle se curven MÁS y aún sean consideradas "ortogonales".
    # Este es el valor más crítico para la flexibilidad visual de la ruta Manhattan.
    # Recomendado: 5 a 15 grados.
    TOLERANCIA_MANHATTAN_SEGMENTO_GRADOS = 12 # Ajustado para mayor flexibilidad en la rectitud de las calles

app.config.from_object(Config)

@app.route('/')
def index():
    return render_template("index.html")

def pedir_ruta_osrm(p1, p2, perfil='driving'):
    """
    Realiza una solicitud al servidor OSRM para obtener una ruta entre dos puntos.
    Incluye manejo de errores y conversión de formato.
    """
    base_url = f"{app.config['OSRM_BASE_URL']}{perfil}/"
    coords = f"{p1['lng']},{p1['lat']};{p2['lng']},{p2['lat']}"
    
    # Añadimos 'alternatives=false' y 'steps=false' para una respuesta más concisa
    # (solo la ruta principal y sin detalles de navegación paso a paso).
    url = f"{base_url}{coords}?overview=full&geometries=geojson&alternatives=false&steps=false"
    
    try:
        resp = requests.get(url, timeout=app.config['OSRM_TIMEOUT_SECONDS']) 
        resp.raise_for_status() # Lanza una excepción para errores HTTP (4xx o 5xx)
        data = resp.json()

        # Verifica si OSRM respondió con un error de código o si no encontró rutas
        if data.get("code") != "Ok" or not data.get("routes"):
            error_message = data.get("message", "Error desconocido de OSRM.")
            if data.get("code") == "NoRoute":
                raise Exception(f"OSRM: No se encontró ruta entre los puntos. Podrían estar desconectados en la red vial o demasiado lejos. Mensaje: {error_message}")
            else:
                raise Exception(f"Error OSRM inesperado ({data.get('code')}): {error_message}. URL: {url}")
        
        ruta = data["routes"][0]["geometry"]["coordinates"]
        distancia = data["routes"][0]["distance"] # en metros
        duracion = data["routes"][0]["duration"]   # en segundos

        # OSRM devuelve (lng, lat), Leaflet suele usar (lat, lng)
        ruta_latlng = [(lat, lng) for lng, lat in ruta]
        return ruta_latlng, distancia, duracion
    
    except requests.exceptions.Timeout:
        raise Exception(f"La solicitud a OSRM ha excedido el tiempo de espera ({app.config['OSRM_TIMEOUT_SECONDS']}s).")
    except requests.exceptions.ConnectionError:
        raise Exception("No se pudo conectar al servidor OSRM. Verifica tu conexión a internet o el estado del servidor.")
    except requests.exceptions.RequestException as e:
        raise Exception(f"Error general al obtener datos de OSRM: {e}")
    except Exception as e:
        raise Exception(f"Ocurrió un error inesperado en pedir_ruta_osrm: {e}")

def validar_ruta_por_segmentos_ortogonales(ruta_osrm_latlng, tolerancia_grados_segmento):
    """
    Verifica que CADA segmento de la ruta OSRM sea aproximadamente ortogonal (horizontal o vertical).
    Si un solo segmento se desvía demasiado de un ángulo cardinal (0, 90, 180, 270),
    la ruta completa se considera no ortogonal para el propósito de Manhattan.
    """
    if len(ruta_osrm_latlng) < 2:
        return True # Una ruta con menos de 2 puntos no tiene segmentos para validar

    for i in range(len(ruta_osrm_latlng) - 1):
        lat1, lng1 = ruta_osrm_latlng[i]
        lat2, lng2 = ruta_osrm_latlng[i+1]

        dx = lng2 - lng1
        dy = lat2 - lat1
        
        # Ignorar segmentos muy pequeños (casi puntos idénticos) para evitar problemas de flotantes
        if isclose(dx, 0, abs_tol=1e-7) and isclose(dy, 0, abs_tol=1e-7):
            continue 

        # Calcular el ángulo del segmento en grados (0 a 360)
        angulo = degrees(atan2(dy, dx)) % 360 

        angulos_cardinales = [0, 90, 180, 270]
        
        is_segment_orthogonal = False
        for av in angulos_cardinales:
            # Comprobar si el ángulo está dentro de la tolerancia de un ángulo cardinal
            # Se usan múltiples comprobaciones para manejar la "vuelta" en 0/360 grados
            if abs(angulo - av) <= tolerancia_grados_segmento or \
               abs(angulo - (av - 360)) <= tolerancia_grados_segmento or \
               abs(angulo - (av + 360)) <= tolerancia_grados_segmento:
                is_segment_orthogonal = True
                break
        
        if not is_segment_orthogonal:
            # Si un segmento no es ortogonal, toda la ruta no lo es.
            # print(f"DEBUG: Segmento no ortogonal detectado: ({lat1:.4f},{lng1:.4f}) a ({lat2:.4f},{lng2:.4f}), ángulo: {angulo:.2f}°")
            return False 
    return True

def es_ortogonal_tendencia_principal(p1, p2, tolerancia_grados_tendencia):
    """
    Verifica si la línea recta entre dos puntos (la "tendencia" general) es
    aproximadamente ortogonal (horizontal o vertical) dentro de una tolerancia dada.
    """
    dx = p2['lng'] - p1['lng']
    dy = p2['lat'] - p1['lat']

    # Si los puntos son idénticos o casi idénticos, se considera ortogonal
    if isclose(dx, 0, abs_tol=1e-7) and isclose(dy, 0, abs_tol=1e-7):
        return True 

    angulo = degrees(atan2(dy, dx)) % 360
    angulos_cardinales = [0, 90, 180, 270]

    for av in angulos_cardinales:
        if abs(angulo - av) <= tolerancia_grados_tendencia or \
           abs(angulo - (av - 360)) <= tolerancia_grados_tendencia or \
           abs(angulo - (av + 360)) <= tolerancia_grados_tendencia:
            return True
    return False

@app.route('/ruta', methods=['POST'])
def ruta():
    data = request.json
    origen = data.get("origen")
    destino = data.get("destino")
    modo = data.get("modo", "auto")
    perfil = 'driving'
    if modo == 'bici':
        perfil = 'bike'
    elif modo == 'peaton':
        perfil = 'foot'

    if not origen or not destino:
        return jsonify({'error': 'Faltan datos de origen o destino'}), 400

    # --- Calcular Ruta Normal (Dijkstra vía OSRM) ---
    ruta_normal_coords = []
    distancia_normal = 0
    duracion_normal = 0
    mensaje_normal = 'Ruta normal calculada con OSRM.'
    try:
        ruta_normal_coords, distancia_normal, duracion_normal = pedir_ruta_osrm(origen, destino, perfil)
    except Exception as e:
        mensaje_normal = f"Error al calcular ruta normal: {str(e)}"
        print(f"[ERROR OSRM Ruta Normal] {mensaje_normal}") # Log para el servidor
        # Continuar para intentar calcular la ruta Manhattan si se solicitó

    # --- Lógica para la Ruta Manhattan ---
    ruta_manhattan_coords = []
    distancia_manhattan = float('inf') 
    duracion_manhattan = float('inf')
    mensaje_manhattan = "No se pudo calcular una ruta Manhattan ortogonal válida." 

    if modo == "manhattan":
        # Candidatos para el punto de esquina de la "L"
        # Opción 1: horizontal (lat origen) primero, luego vertical (lng destino)
        punto_intermedio_h_v = {'lat': origen['lat'], 'lng': destino['lng']}
        # Opción 2: vertical (lat destino) primero, luego horizontal (lng origen)
        punto_intermedio_v_h = {'lat': destino['lat'], 'lng': origen['lng']}

        candidatos_l_shape = [
            (origen, punto_intermedio_h_v, destino),
            (origen, punto_intermedio_v_h, destino)
        ]
        
        # Para futuras mejoras de flexibilidad: Aquí se podrían añadir más puntos intermedios
        # en una pequeña cuadrícula alrededor de los puntos_intermedios_h_v y _v_h
        # para explorar más opciones si la red vial no es perfectamente cuadriculada.
        # Sin embargo, esto aumenta significativamente el número de llamadas a OSRM.

        for p_start, p_intermedio, p_end in candidatos_l_shape:
            try:
                # 1. Validar la tendencia principal de la "L" geométrica (ej. Origen a Esquina, y Esquina a Destino)
                if not es_ortogonal_tendencia_principal(p_start, p_intermedio, 
                                                        tolerancia_grados_tendencia=app.config['TOLERANCIA_MANHATTAN_TENDENCIA_PRINCIPAL_GRADOS']) or \
                   not es_ortogonal_tendencia_principal(p_intermedio, p_end, 
                                                        tolerancia_grados_tendencia=app.config['TOLERANCIA_MANHATTAN_TENDENCIA_PRINCIPAL_GRADOS']):
                    # print(f"DEBUG: Candidato {p_intermedio} descartado por no cumplir ortogonalidad de tendencia principal.")
                    continue

                # 2. Obtener las rutas reales de OSRM para los dos segmentos de la 'L'
                # OSRM encontrará la ruta más corta en la red vial real para estos segmentos.
                ruta1_osrm, dist1_osrm, dur1_osrm = pedir_ruta_osrm(p_start, p_intermedio, perfil)
                ruta2_osrm, dist2_osrm, dur2_osrm = pedir_ruta_osrm(p_intermedio, p_end, perfil)
                
                # 3. Validar si CADA SEGMENTO de las rutas OSRM obtenidas es suficientemente recto/ortogonal.
                # Esta es la validación que asegura que las calles de la ruta no se curvan demasiado.
                if not validar_ruta_por_segmentos_ortogonales(ruta1_osrm, 
                                                              tolerancia_grados_segmento=app.config['TOLERANCIA_MANHATTAN_SEGMENTO_GRADOS']) or \
                   not validar_ruta_por_segmentos_ortogonales(ruta2_osrm, 
                                                              tolerancia_grados_segmento=app.config['TOLERANCIA_MANHATTAN_SEGMENTO_GRADOS']):
                    # print(f"DEBUG: Candidato {p_intermedio} descartado porque los segmentos reales de OSRM no son lo suficientemente rectos.")
                    continue 

                # Si todas las validaciones pasan, esta es una ruta Manhattan válida
                ruta_manhattan_actual = ruta1_osrm + ruta2_osrm[1:] # Unir las rutas, quitando el punto duplicado
                distancia_total_actual = dist1_osrm + dist2_osrm
                duracion_total_actual = dur1_osrm + dur2_osrm
                
                # Si es la mejor ruta Manhattan encontrada hasta ahora (la más corta), la guardamos
                if distancia_total_actual < distancia_manhattan:
                    ruta_manhattan_coords = ruta_manhattan_actual
                    distancia_manhattan = distancia_total_actual
                    duracion_manhattan = duracion_total_actual
                    mensaje_manhattan = f"Ruta Manhattan encontrada (distancia: {round(distancia_manhattan, 2)}m)."

            except Exception as e:
                # print(f"DEBUG: Error al procesar candidato Manhattan para p_intermedio {p_intermedio}: {e}. Saltando.")
                # Si una de las piernas falla o hay un error, simplemente se descarta este candidato
                continue 
    
    # --- Preparar la respuesta JSON final ---
    response_data = {
        'ruta': ruta_normal_coords,
        'distancia_metros': round(distancia_normal, 2),
        'tiempo_segundos': round(duracion_normal, 2),
        'mensaje': mensaje_normal,
        'ruta_manhattan': ruta_manhattan_coords, # Estará vacía si no se encontró
        'distancia_manhattan_metros': round(distancia_manhattan, 2) if distancia_manhattan != float('inf') else None,
        'tiempo_manhattan_segundos': round(duracion_manhattan, 2) if duracion_manhattan != float('inf') else None,
        'mensaje_manhattan': mensaje_manhattan
    }

    # Si ninguna ruta (normal o manhattan) pudo ser calculada, podemos devolver un error HTTP
    if not ruta_normal_coords and not ruta_manhattan_coords:
         # Considera un código de estado 404 o 500 dependiendo de si la ausencia de ruta es esperada
         return jsonify(response_data), 404 
         
    return jsonify(response_data)

@app.route('/favicon.ico')
def favicon():
    """Sirve el favicon para el navegador."""
    return send_from_directory(os.path.join(app.root_path, 'static'),
                               'favicon.ico', mimetype='image/vnd.microsoft.icon')

if __name__ == '__main__':
    # Obtener el puerto desde la variable de entorno, si no está presente usar el puerto 5000
    port = int(os.environ.get('PORT', 5000))
    # 'debug=True' es útil para desarrollo: recarga el servidor automáticamente y muestra errores detallados.
    # ¡Desactívalo en producción!
    app.run(host='0.0.0.0', port=port, debug=True)