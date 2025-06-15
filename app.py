from flask import Flask, render_template, request, jsonify, send_from_directory
import os
import requests
from math import isclose, atan2, degrees

app = Flask(__name__)

@app.route('/')
def index():
    return render_template("index.html")

def pedir_ruta_osrm(p1, p2, perfil='driving'):
    base_url = f"http://router.project-osrm.org/route/v1/{perfil}/"
    coords = f"{p1['lng']},{p1['lat']};{p2['lng']},{p2['lat']}"
    url = f"{base_url}{coords}?overview=full&geometries=geojson"
    
    try:
        resp = requests.get(url, timeout=10) # Añadir timeout
        resp.raise_for_status() # Lanza una excepción para errores HTTP (4xx o 5xx)
        data = resp.json()
        if data["code"] != "Ok":
            error_message = data.get("message", "Error OSRM desconocido")
            raise Exception(f"Error OSRM: {error_message}")
        
        ruta = data["routes"][0]["geometry"]["coordinates"]
        distancia = data["routes"][0]["distance"]
        duracion = data["routes"][0]["duration"]
        # Convertir a lat,lng para Leaflet
        ruta_latlng = [(lat, lng) for lng, lat in ruta]
        return ruta_latlng, distancia, duracion
    except requests.exceptions.Timeout:
        raise Exception("OSRM request timed out.")
    except requests.exceptions.ConnectionError:
        raise Exception("Could not connect to OSRM server.")
    except requests.exceptions.RequestException as e:
        raise Exception(f"Error fetching OSRM data: {e}")
    except Exception as e:
        raise Exception(f"An unexpected error occurred in pedir_ruta_osrm: {e}")

# Renombramos y modificamos esta función para que valide CADA segmento de la ruta OSRM
def validar_ruta_por_segmentos_ortogonales(ruta_osrm_latlng, tolerancia_grados_segmento=10):
    """
    Verifica que CADA segmento de la ruta OSRM sea aproximadamente ortogonal.
    Si cualquier segmento se desvía demasiado, la ruta completa no es ortogonal.
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
               abs(angulo - (av - 360)) <= tolerancia_grados_segmento or \
               abs(angulo - (av + 360)) <= tolerancia_grados_segmento:
                is_segment_orthogonal = True
                break
        
        if not is_segment_orthogonal:
            # print(f"Segmento no ortogonal: ({lat1:.4f},{lng1:.4f}) a ({lat2:.4f},{lng2:.4f}), ángulo: {angulo:.2f}°")
            return False # Un solo segmento no ortogonal hace que toda la ruta no lo sea
    return True

# Esta función es para verificar la tendencia principal de los dos tramos de la "L"
def es_ortogonal_tendencia_principal(p1, p2, tolerancia_grados_tendencia=10):
    """
    Verifica si la línea recta entre dos puntos es aproximadamente ortogonal.
    Esto es para la intención general del tramo, no para cada segmento.
    """
    dx = p2['lng'] - p1['lng']
    dy = p2['lat'] - p1['lat']

    if isclose(dx, 0, abs_tol=1e-7) and isclose(dy, 0, abs_tol=1e-7):
        return True # Puntos idénticos

    angulo = degrees(atan2(dy, dx)) % 360
    angulos_validos = [0, 90, 180, 270]

    for av in angulos_validos:
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
        return jsonify({'error': 'Faltan datos origen o destino'}), 400

    try:
        ruta_normal, dist_normal, dur_normal = pedir_ruta_osrm(origen, destino, perfil)
    except Exception as e:
        print(f"Error en ruta normal: {e}") # Para depuración en consola del servidor
        return jsonify({'error': f'Error calculando ruta normal: {str(e)}'}), 500

    # Lógica para la ruta Manhattan
    if modo == "manhattan":
        puntos_intermedios_candidatos = [
            {'lat': origen['lat'], 'lng': destino['lng']}, # Opción 1: horizontal primero, luego vertical
            {'lat': destino['lat'], 'lng': origen['lng']}  # Opción 2: vertical primero, luego horizontal
        ]

        mejor_ruta_manhattan = None
        mejor_dist_manhattan = float('inf') 
        mejor_dur_manhattan = float('inf')

        for p_intermedio_candidato in puntos_intermedios_candidatos:
            # 1. Validar la tendencia principal: ¿La "esquina" geométrica es ortogonal?
            tolerancia_tendencia = 30 # Tolerancia para la línea recta Origen->Intermedio y Intermedio->Destino
            if not es_ortogonal_tendencia_principal(origen, p_intermedio_candidato, tolerancia_grados_tendencia=tolerancia_tendencia) or \
               not es_ortogonal_tendencia_principal(p_intermedio_candidato, destino, tolerancia_grados_tendencia=tolerancia_tendencia):
                # print(f"Candidato descartado por no cumplir ortogonalidad de tendencia principal para p_intermedio: {p_intermedio_candidato}")
                continue

            try:
                # 2. Obtener las rutas reales de OSRM para los dos segmentos
                ruta1_osrm, dist1_osrm, dur1_osrm = pedir_ruta_osrm(origen, p_intermedio_candidato, perfil)
                ruta2_osrm, dist2_osrm, dur2_osrm = pedir_ruta_osrm(p_intermedio_candidato, destino, perfil)
                
                # 3. **AHORA VALIDAR CADA SEGMENTO REAL DE LAS RUTAS OSRM**
                # Esta es la validación estricta para asegurar que las calles sean rectas
                tolerancia_segmento = 10 # Tolerancia para la "rectitud" de cada mini-segmento de la calle
                if not validar_ruta_por_segmentos_ortogonales(ruta1_osrm, tolerancia_grados_segmento=tolerancia_segmento) or \
                   not validar_ruta_por_segmentos_ortogonales(ruta2_osrm, tolerancia_grados_segmento=tolerancia_segmento):
                    # print(f"Candidato descartado porque los segmentos reales de OSRM no son lo suficientemente rectos para p_intermedio: {p_intermedio_candidato}")
                    continue # Si OSRM nos da una ruta curva, descartamos este candidato

                ruta_manhattan_actual = ruta1_osrm + ruta2_osrm[1:] # Unir las rutas, quitando el punto duplicado
                distancia_total_actual = dist1_osrm + dist2_osrm
                duracion_total_actual = dur1_osrm + dur2_osrm
                
                if distancia_total_actual < mejor_dist_manhattan:
                    mejor_ruta_manhattan = ruta_manhattan_actual
                    mejor_dist_manhattan = distancia_total_actual
                    mejor_dur_manhattan = duracion_total_actual

            except Exception as e:
                # print(f"Error al calcular segmento OSRM para Manhattan: {e}. Saltando este candidato.")
                continue 

        if mejor_ruta_manhattan:
            return jsonify({
                'ruta': ruta_normal,
                'ruta_manhattan': mejor_ruta_manhattan,
                'distancia_metros': round(dist_normal, 2),
                'tiempo_segundos': round(dur_normal, 2),
                'mensaje': 'Ruta normal calculada con OSRM',
                'mensaje_manhattan': 'Ruta Manhattan válida encontrada y mostrada.'
            })
        else:
            return jsonify({
                'ruta': ruta_normal,
                'distancia_metros': round(dist_normal, 2),
                'tiempo_segundos': round(dur_normal, 2),
                'mensaje': 'Ruta normal calculada con OSRM',
                'mensaje_manhattan': 'No se pudo calcular una ruta Manhattan ortogonal válida. Solo se muestra ruta normal.'
            })

    else:
        # Si el modo no es manhattan, solo se devuelve la ruta normal
        return jsonify({
            'ruta': ruta_normal,
            'distancia_metros': round(dist_normal, 2),
            'tiempo_segundos': round(dur_normal, 2),
            'mensaje': 'Ruta normal calculada con OSRM'
        })

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'),
                               'favicon.ico', mimetype='image/vnd.microsoft.icon')

if __name__ == '__main__':
    # Obtener el puerto desde la variable de entorno, si no está presente usar el puerto 5000
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)