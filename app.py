from flask import Flask, render_template, request, jsonify, send_from_directory
import os
import osmnx as ox
import networkx as nx
import math

app = Flask(__name__)

# Descargar el grafo automáticamente al arrancar
print("Descargando grafo de CDMX y Edo. Mex desde OpenStreetMap...")
lugares = [
    "Ciudad de México, Mexico",
    "Estado de México, Mexico"
]
G = ox.graph_from_place(lugares, network_type="drive")
G = G.to_undirected()
print("Grafo cargado en memoria.")

# Ángulo en grados entre dos nodos, de 0 a 180
def angulo(u, v):
    x1, y1 = G.nodes[u]['x'], G.nodes[u]['y']
    x2, y2 = G.nodes[v]['x'], G.nodes[v]['y']
    dx = x2 - x1
    dy = y2 - y1
    angle = math.degrees(math.atan2(dy, dx)) % 180
    return angle

# Verificar si es una calle "casi ortogonal"
def es_recta(u, v, tolerancia_angulo=9, tolerancia_dist=9):
    ang = angulo(u, v)

    if abs(ang - 0) <= tolerancia_angulo or abs(ang - 180) <= tolerancia_angulo:
        y1, y2 = G.nodes[u]['y'], G.nodes[v]['y']
        if abs(y1 - y2) <= tolerancia_dist:
            return True

    if abs(ang - 90) <= tolerancia_angulo:
        x1, x2 = G.nodes[u]['x'], G.nodes[v]['x']
        if abs(x1 - x2) <= tolerancia_dist:
            return True

    return False

# Crear grafo Manhattan solo con calles ortogonales
def grafo_manhattan():
    H = nx.Graph()
    for u, v, data in G.edges(data=True):
        if es_recta(u, v):
            H.add_edge(u, v, **data)
    return H

@app.route('/')
def index():
    return render_template("index.html")

@app.route('/ruta', methods=['POST'])
def ruta():
    data = request.json
    origen = data["origen"]
    destino = data["destino"]

    nodo_origen = ox.distance.nearest_nodes(G, origen['lng'], origen['lat'])
    nodo_destino = ox.distance.nearest_nodes(G, destino['lng'], destino['lat'])

    ruta_dijkstra = nx.shortest_path(G, nodo_origen, nodo_destino, weight='length')
    ruta_coords_dijkstra = [(G.nodes[n]['y'], G.nodes[n]['x']) for n in ruta_dijkstra]
    distancia_dijkstra = sum(G[u][v][0]['length'] for u, v in zip(ruta_dijkstra[:-1], ruta_dijkstra[1:]))

    manhattan_coords = []
    mensaje_manhattan = None
    try:
        H = grafo_manhattan()
        if H.has_node(nodo_origen) and H.has_node(nodo_destino):
            ruta_manhattan = nx.shortest_path(H, nodo_origen, nodo_destino, weight='length')
            manhattan_coords = [(G.nodes[n]['y'], G.nodes[n]['x']) for n in ruta_manhattan]
        else:
            mensaje_manhattan = "No se pudo calcular la ruta Manhattan: nodos no conectados en calles ortogonales."
    except Exception:
        mensaje_manhattan = "No se pudo calcular la ruta Manhattan: no hay conexión solo por calles ortogonales."

    return jsonify({
        'ruta': ruta_coords_dijkstra,
        'distancia_metros': round(distancia_dijkstra, 2),
        'ruta_manhattan': manhattan_coords,
        'mensaje_manhattan': mensaje_manhattan
    })

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'),
                               'favicon.ico', mimetype='image/vnd.microsoft.icon')

if __name__ == '__main__':
    # Obtener el puerto desde la variable de entorno, si no está presente usar el puerto 5000
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)