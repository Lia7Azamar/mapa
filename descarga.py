import osmnx as ox
import networkx as nx

# Cargar los grafos
G1 = ox.load_graphml("cdmx.graphml")
G2 = ox.load_graphml("edomex.graphml")

# Fusionar
G = nx.compose(G1, G2)
G = G.to_undirected()

# Guardar el grafo combinado
ox.save_graphml(G, "edomex_cdmx_combinado.graphml")
