from flask import Flask, render_template, request, jsonify, send_from_directory
import os
import requests
from math import isclose, atan2, degrees

app = Flask(__name__)

@app.route('/')
def index():
    return render_template("index.html")

def pedir_ruta_osrm(p1, p2, perfil='driving'):
    # Public OSRM demo server. No para uso en producción de alto volumen.
    base_url = f"http://router.project-osrm.org/route/v1/{perfil}/"
    coords = f"{p1['lng']},{p1['lat']};{p2['lng']},{p2['lat']}"
    # overview=full: devuelve todos los puntos de la geometría
    # geometries=geojson: formato de la geometría
    # steps=false: no devuelve instrucciones paso a paso (reduce tamaño de respuesta)
    # alternatives=false: no busca rutas alternativas (reduce tiempo de cálculo)
    url = f"{base_url}{coords}?overview=full&geometries=geojson&steps=false&alternatives=false" 
    
    try:
        # Aumentar el timeout si la ruta es muy larga o el servidor OSRM está ocupado.
        # No un valor excesivo para no colgar la aplicación.
        resp = requests.get(url, timeout=15) 
        resp.raise_for_status() # Lanza una excepción para errores HTTP (4xx o 5xx)
        data = resp.json()
        
        # OSRM devuelve "Ok" incluso si no encuentra ruta, pero then data["routes"] está vacío.
        if data["code"] != "Ok" or not data.get("routes"):
            error_message = data.get("message", "NoRoute o error OSRM desconocido")
            if data["code"] == "NoRoute":
                 raise Exception(f"OSRM: No se encontró ruta entre los puntos: {error_message}. Podrían estar desconectados en la red vial.")
            else:
                 raise Exception(f"Error OSRM inesperado ({data['code']}): {error_message}")
        
        ruta = data["routes"][0]["geometry"]["coordinates"]
        distancia = data["routes"][0]["distance"] # en metros
        duracion = data["routes"][0]["duration"]   # en segundos

        # Convertir de (lng, lat) de GeoJSON a (lat, lng) de Leaflet
        ruta_latlng = [(lat, lng) for lng, lat in ruta]
        return ruta_latlng, distancia, duracion
    
    except requests.exceptions.Timeout:
        raise Exception("Solicitud a OSRM ha excedido el tiempo de espera.")
    except requests.exceptions.ConnectionError:
        raise Exception("No se pudo conectar al servidor OSRM. Verifica tu conexión a internet o el estado del servidor.")
    except requests.exceptions.RequestException as e:
        # Captura otros errores de request (ej. DNS, SSL, etc.)
        raise Exception(f"Error al obtener datos de OSRM: {e}")
    except Exception as e:
        # Captura cualquier otra excepción inesperada en esta función
        raise Exception(f"Ocurrió un error inesperado al pedir ruta a OSRM: {e}")

# Mantener esta función pero ya NO se usará para validar CADA SEGMENTO DE LA RUTA REAL DE OSRM
# Su propósito ahora sería solo si quieres una validación extremadamente estricta en otro contexto.
def validar_ruta_por_segmentos_ortogonales(ruta_osrm_latlng, tolerancia_grados_segmento=10):
    """
    Verifica que CADA segmento de la ruta OSRM sea aproximadamente ortogonal.
    Es una validación muy estricta y puede descartar muchas rutas reales.
    """
    for i in range(len(ruta_osrm_latlng) - 1):
        lat1, lng1 = ruta_osrm_latlng[i]
        lat2, lng2 = ruta_osrm_latlng[i+1]

        dx = lng2 - lng1
        dy = lat2 - lat1
        
        # Ignorar segmentos muy pequeños para evitar ruido de flotantes o puntos idénticos
        if isclose(dx, 0, abs_tol=1e-7) and isclose(dy, 0, abs_tol=1e-7):
            continue 

        angulo = degrees(atan2(dy, dx)) % 360 # ángulo en grados entre 0 y 360

        angulos_validos = [0, 90, 180, 270]
        
        is_segment_orthogonal = False
        for av in angulos_validos:
            if abs(angulo - av) <= tolerancia_grados_segmento or \
               abs(angulo - (av - 360)) <= tolerancia_grados_segmento: 
                is_segment_orthogonal = True
                break
        
        if not is_segment_orthogonal:
            return False # Un solo segmento no ortogonal hace que toda la ruta no lo sea
    return True

# Función para verificar la ortogonalidad de una línea recta entre dos puntos
def is_line_segment_orthogonal(p1_coords, p2_coords, tolerancia_grados=10):
    """
    Verifica si la línea recta (geodésica) entre dos puntos (lat, lng) 
    es aproximadamente ortogonal (horizontal o vertical) dentro de una tolerancia dada.
    Esto se usa para la 'intención' de la L de Manhattan, no para cada calle.
    """
    lat1, lng1 = p1_coords
    lat2, lng2 = p2_coords

    dx = lng2 - lng1 # Diferencia en longitud
    dy = lat2 - lat1 # Diferencia en latitud
    
    # Si los puntos son idénticos o casi idénticos, considerarlos ortogonales
    if isclose(dx, 0, abs_tol=1e-7) and isclose(dy, 0, abs_tol=1e-7):
        return True 

    # Calcular el ángulo en grados (0-360)
    angulo = degrees(atan2(dy, dx)) % 360 

    # Ángulos cardinales ideales (N, E, S, O)
    angulos_cardinales = [0, 90, 180, 270]
    
    for av in angulos_cardinales:
        # Comprobar la cercanía al ángulo cardinal, considerando el "wrap around" (ej. 350 es cerca de 0/360)
        if abs(angulo - av) <= tolerancia_grados or \
           abs(angulo - (av - 360)) <= tolerancia_grados or \
           abs(angulo - (av + 360)) <= tolerancia_grados: # Último es más por robustez, %360 ya lo maneja
            return True
            
    return False


@app.route('/ruta', methods=['POST'])
def ruta():
    data = request.json
    origen = data.get("origen") # {'lat': ..., 'lng': ...}
    destino = data.get("destino") # {'lat': ..., 'lng': ...}
    modo = data.get("modo", "auto") # auto, bici, peaton, manhattan
    
    perfil_osrm = 'driving'
    if modo == 'bici':
        perfil_osrm = 'bike'
    elif modo == 'peaton':
        perfil_osrm = 'foot'

    if not origen or not destino:
        return jsonify({'error': 'Faltan datos de origen o destino'}), 400

    # --- 1. Calcular Ruta Normal (Dijkstra vía OSRM) ---
    ruta_normal_coords = []
    distancia_normal = 0
    duracion_normal = 0
    mensaje_dijkstra = None
    try:
        ruta_normal_coords, distancia_normal, duracion_normal = pedir_ruta_osrm(origen, destino, perfil_osrm)
        mensaje_dijkstra = "Ruta normal calculada con OSRM."
    except Exception as e:
        mensaje_dijkstra = f"Error al calcular ruta normal: {str(e)}"
        print(f"[ERROR] {mensaje_dijkstra}")
        # Se sigue intentando la ruta Manhattan aunque la normal falle, por si acaso.

    # --- 2. Lógica para la Ruta Manhattan ---
    ruta_manhattan_coords = []
    distancia_manhattan = float('inf') 
    duracion_manhattan = float('inf')
    mensaje_manhattan = "No se pudo calcular una ruta Manhattan ortogonal válida." # Mensaje por defecto

    if modo == "manhattan":
        # Candidatos para el punto de esquina de la "L"
        # Opción 1: horizontal (misma latitud que origen, misma longitud que destino)
        punto_intermedio_h_v = {'lat': origen['lat'], 'lng': destino['lng']}
        # Opción 2: vertical (misma latitud que destino, misma longitud que origen)
        punto_intermedio_v_h = {'lat': destino['lat'], 'lng': origen['lng']}

        candidatos_l_shape = [
            (origen, punto_intermedio_h_v, destino), # Origen -> Intermedio_H_V -> Destino
            (origen, punto_intermedio_v_h, destino)  # Origen -> Intermedio_V_H -> Destino
        ]
        
        # Tolerancia para la "ortogonalidad" de la FORMA DE L de Manhattan (la línea recta entre puntos)
        # Un valor entre 5 y 20 grados es flexible pero mantiene la intención de ortogonalidad.
        # Si las calles no están cerca de ser cardinales, esta L no se formará.
        tolerancia_l_shape_grados = 15 

        for p_start, p_intermedio, p_end in candidatos_l_shape:
            try:
                # Validar la tendencia geométrica de la primera pierna de la L: (Origen -> Punto Intermedio)
                if not is_line_segment_orthogonal((p_start['lat'], p_start['lng']), 
                                                  (p_intermedio['lat'], p_intermedio['lng']), 
                                                  tolerancia_grados=tolerancia_l_shape_grados):
                    # print(f"DEBUG: Candidato descartado (pierna 1 de L no ortogonal para intermedio: {p_intermedio['lat']:.4f},{p_intermedio['lng']:.4f})")
                    continue

                # Validar la tendencia geométrica de la segunda pierna de la L: (Punto Intermedio -> Destino)
                if not is_line_segment_orthogonal((p_intermedio['lat'], p_intermedio['lng']), 
                                                  (p_end['lat'], p_end['lng']), 
                                                  tolerancia_grados=tolerancia_l_shape_grados):
                    # print(f"DEBUG: Candidato descartado (pierna 2 de L no ortogonal para intermedio: {p_intermedio['lat']:.4f},{p_intermedio['lng']:.4f})")
                    continue

                # Si las tendencias principales son ortogonales, pedir las rutas reales a OSRM para estos dos segmentos.
                # OSRM encontrará la ruta más corta en la red vial REAL para ir de un punto a otro.
                ruta1_osrm_coords, dist1_osrm, dur1_osrm = pedir_ruta_osrm(p_start, p_intermedio, perfil_osrm)
                ruta2_osrm_coords, dist2_osrm, dur2_osrm = pedir_ruta_osrm(p_intermedio, p_end, perfil_osrm)
                
                # Unir las rutas. El punto intermedio es el final de ruta1 y el inicio de ruta2,
                # por lo que se quita el primer punto de ruta2 para evitar duplicados.
                current_manhattan_path = ruta1_osrm_coords + ruta2_osrm_coords[1:]
                current_manhattan_distance = dist1_osrm + dist2_osrm
                current_manhattan_duration = dur1_osrm + dur2_osrm

                # Comparar con la mejor ruta Manhattan encontrada hasta ahora
                if current_manhattan_distance < distancia_manhattan:
                    distancia_manhattan = current_manhattan_distance
                    duracion_manhattan = current_manhattan_duration
                    ruta_manhattan_coords = current_manhattan_path
                    mensaje_manhattan = f"Ruta Manhattan encontrada (distancia: {round(distancia_manhattan, 2)}m)."

            except Exception as e:
                # Si OSRM falla para alguna pierna o hay otro error, se descarta este candidato de 'L'
                # print(f"DEBUG: Error al calcular segmento OSRM para candidato Manhattan ({p_intermedio}): {e}")
                continue 
        
        # Si no se encontró ninguna ruta Manhattan válida después de revisar todos los candidatos
        if not ruta_manhattan_coords:
            mensaje_manhattan = "No se pudo encontrar una ruta Manhattan con la configuración actual (puede que las calles no formen una cuadrícula clara en esa zona)."
            # Si la ruta normal se calculó con éxito, se seguirá devolviendo.

    # --- 3. Preparar la respuesta final ---
    response_data = {
        'ruta': ruta_normal_coords,
        'distancia_metros': round(distancia_normal, 2),
        'tiempo_segundos': round(duracion_normal, 2),
        'mensaje': mensaje_dijkstra, # Mensaje sobre la ruta normal
        'ruta_manhattan': ruta_manhattan_coords,
        'distancia_manhattan_metros': round(distancia_manhattan, 2) if distancia_manhattan != float('inf') else None,
        'tiempo_manhattan_segundos': round(duracion_manhattan, 2) if duracion_manhattan != float('inf') else None,
        'mensaje_manhattan': mensaje_manhattan
    }

    # Si ninguna de las rutas (normal o manhattan) se pudo calcular, se devuelve un error 500
    if not ruta_normal_coords and not ruta_manhattan_coords:
         return jsonify(response_data), 500
         
    return jsonify(response_data)

@app.route('/favicon.ico')
def favicon():
    # Siempre es buena práctica tener un favicon
    return send_from_directory(os.path.join(app.root_path, 'static'),
                               'favicon.ico', mimetype='image/vnd.microsoft.icon')

if __name__ == '__main__':
    # Obtener el puerto desde la variable de entorno, si no está presente usar el puerto 5000
    port = int(os.environ.get('PORT', 5000))
    # debug=True es útil para desarrollo, ya que recarga el servidor automáticamente con cambios y muestra errores.
    app.run(host='0.0.0.0', port=port, debug=True)