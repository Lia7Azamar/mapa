// Capas base
const osmStandard = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19,
  attribution: '© OpenStreetMap'
});

const esriSat = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
  maxZoom: 19,
  attribution: 'Tiles © Esri'
});

// Inicializa el mapa
const map = L.map('map', {
  center: [19.4326, -99.1332],
  zoom: 13,
  layers: [osmStandard]
});

// Control capas base
const baseMaps = {
  "Mapa estándar": osmStandard,
  "Satélite (Esri)": esriSat,
};
L.control.layers(baseMaps, null, { position: 'topleft' }).addTo(map);

// Variables
let puntos = [null, null];
let markers = [null, null];
let rutaLine = null;
let modoSeleccion = null;
let modoTransporte = "";
let infoDiv = document.getElementById('info');
let btnOrigen = document.getElementById('btnOrigen');
let btnDestino = document.getElementById('btnDestino');
let selectTransporte = document.getElementById('transporte');
let datosPuntosDiv = document.getElementById('datosPuntos');
let marcadorBusqueda = null;
window.rutaManhattanLine = null;

const velocidades = {
  auto: 11.1,
  bici: 5.5,
  peaton: 1.4
};

// Activar botones cuando se elige transporte
selectTransporte.addEventListener('change', (e) => {
  modoTransporte = e.target.value;
  btnOrigen.disabled = !modoTransporte;
  btnDestino.disabled = !modoTransporte;
  infoDiv.querySelector('p').textContent = modoTransporte ? 'Selecciona origen o destino.' : 'Selecciona un modo de transporte antes de elegir puntos.';
  modoSeleccion = null;
});

// Botones
btnOrigen.addEventListener('click', () => modoSeleccion = 'origen');
btnDestino.addEventListener('click', () => modoSeleccion = 'destino');

function resetMarkers() {
  markers.forEach(m => { if (m) map.removeLayer(m); });
  markers = [null, null];
  puntos = [null, null];
  if (rutaLine) {
    map.removeLayer(rutaLine);
    rutaLine = null;
  }
  if (window.rutaManhattanLine) {
    map.removeLayer(window.rutaManhattanLine);
    window.rutaManhattanLine = null;
  }
  modoSeleccion = null;
  modoTransporte = "";
  selectTransporte.value = "";
  btnOrigen.disabled = true;
  btnDestino.disabled = true;
  infoDiv.querySelector('p').textContent = 'Selecciona un modo de transporte antes de elegir puntos.';
  datosPuntosDiv.innerHTML = "";

  if (marcadorBusqueda) {
    map.removeLayer(marcadorBusqueda);
    marcadorBusqueda = null;
  }

  const tiempoDiv = document.getElementById('info-tiempo');
  if (tiempoDiv) tiempoDiv.remove();
}

function agregarPunto(latlng, tipo) {
  if (tipo === 'origen') {
    puntos[0] = latlng;
    if (markers[0]) map.removeLayer(markers[0]);
    markers[0] = L.marker(latlng).addTo(map).bindPopup("Origen").openPopup();
  } else {
    puntos[1] = latlng;
    if (markers[1]) map.removeLayer(markers[1]);
    markers[1] = L.marker(latlng).addTo(map).bindPopup("Destino").openPopup();
  }

  obtenerInfoLugar(latlng, tipo);

  if (puntos[0] && puntos[1]) {
    if (!modoTransporte) {
      alert("Selecciona un modo de transporte válido antes de calcular la ruta.");
      return;
    }
    calcularRuta();
  }
}

function obtenerInfoLugar(latlng, tipo) {
  const url = `https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat=${latlng.lat}&lon=${latlng.lng}`;
  fetch(url)
    .then(resp => resp.json())
    .then(data => {
      const address = data.address || {};
      const infoHTML = `
        <h4>${tipo === 'origen' ? 'Origen' : 'Destino'}</h4>
        <p><b>Dirección:</b> ${data.display_name || 'No disponible'}</p>
        <p><b>Colonia / Barrio:</b> ${address.neighbourhood || address.suburb || 'No disponible'}</p>
        <p><b>Código Postal:</b> ${address.postcode || 'No disponible'}</p>
        <p><b>Alcaldía / Municipio:</b> ${address.city_district || address.county || address.city || 'No disponible'}</p>
      `;
      let existingDiv = document.getElementById(`info-${tipo}`);
      if (existingDiv) {
        existingDiv.innerHTML = infoHTML;
      } else {
        const div = document.createElement('div');
        div.id = `info-${tipo}`;
        div.style.marginBottom = '1em';
        div.innerHTML = infoHTML;
        datosPuntosDiv.appendChild(div);
      }
    })
    .catch(() => alert('Error al obtener información del lugar'));
}

function calcularRuta() {
  fetch('/ruta', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      origen: { lat: puntos[0].lat, lng: puntos[0].lng },
      destino: { lat: puntos[1].lat, lng: puntos[1].lng },
      modo: modoTransporte
    })
  })
    .then(response => response.json())
    .then(data => {
      const { ruta, distancia_metros, ruta_manhattan, mensaje_manhattan } = data;

      if (rutaLine) {
        map.removeLayer(rutaLine);
      }
      rutaLine = L.polyline(ruta, { color: 'blue', weight: 5 }).addTo(map);
      map.fitBounds(rutaLine.getBounds());

      if (window.rutaManhattanLine) {
        map.removeLayer(window.rutaManhattanLine);
        window.rutaManhattanLine = null;
      }

      if (ruta_manhattan && ruta_manhattan.length > 0) {
        window.rutaManhattanLine = L.polyline(ruta_manhattan, {
          color: 'red',
          weight: 4,
          dashArray: '6, 6'
        }).addTo(map);
      } else if (mensaje_manhattan) {
        alert(mensaje_manhattan);
      }

      const velocidad = velocidades[modoTransporte] || velocidades.auto;
      const tiempo_minutos = distancia_metros / velocidad / 60;

      const tiempoHTML = `
        <p><strong>Distancia:</strong> ${(distancia_metros / 1000).toFixed(2)} km</p>
        <p><strong>Tiempo estimado (${modoTransporte}):</strong> ${tiempo_minutos.toFixed(1)} minutos</p>
        ${mensaje_manhattan ? `<p style="color:red;"><strong>Manhattan:</strong> ${mensaje_manhattan}</p>` : ''}
        <button id="btnReset">Nueva búsqueda</button>
      `;

      let tiempoDiv = document.getElementById('info-tiempo');
      if (!tiempoDiv) {
        tiempoDiv = document.createElement('div');
        tiempoDiv.id = 'info-tiempo';
        infoDiv.appendChild(tiempoDiv);
      }
      tiempoDiv.innerHTML = tiempoHTML;

      document.getElementById('btnReset').addEventListener('click', resetMarkers);
    })
    .catch(() => alert("Error al calcular la ruta"));
}

// Clic en mapa
map.on('click', (e) => {
  if (!modoSeleccion) return;
  agregarPunto(e.latlng, modoSeleccion);
  modoSeleccion = null;
});

// Búsqueda (Leaflet GeoSearch)
const provider = new window.GeoSearch.OpenStreetMapProvider({
  params: { countrycodes: 'mx' }
});
const searchControl = new GeoSearch.GeoSearchControl({
  provider,
  style: 'bar',
  autoComplete: true,
  autoCompleteDelay: 250,
  showMarker: false,
  retainZoomLevel: false,
  searchLabel: 'Buscar dirección',
  keepResult: true
});
map.addControl(searchControl);

map.on('geosearch/showlocation', (result) => {
  const latlng = {
    lat: result.location.y,
    lng: result.location.x
  };

  if (marcadorBusqueda) {
    map.removeLayer(marcadorBusqueda);
  }

  marcadorBusqueda = L.marker(latlng).addTo(map);
  marcadorBusqueda
    .bindPopup(`Resultado de búsqueda:<br>${result.location.label}`)
    .openPopup();

  marcadorBusqueda.on('popupclose', () => {
    map.removeLayer(marcadorBusqueda);
    marcadorBusqueda = null;
  });

  map.setView(latlng, 16);

  const input = document.querySelector('.leaflet-control-geosearch form input');
  if (input) {
    input.value = '';
    input.blur();
  }
  searchControl.clear();
});
