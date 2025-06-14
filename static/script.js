// Asegurarse de que el DOM esté completamente cargado antes de ejecutar el script
document.addEventListener('DOMContentLoaded', () => {

    // --- Capas base y mapa ---
    const osmStandard = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '© OpenStreetMap contributors'
    });

    const esriSat = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
        maxZoom: 19,
        attribution: 'Tiles © Esri'
    });

    const map = L.map('map', {
        center: [19.4326, -99.1332],
        zoom: 13,
        layers: [osmStandard]
    });

    const baseMaps = {
        "Mapa estándar": osmStandard,
        "Satélite (Esri)": esriSat,
    };
    L.control.layers(baseMaps, null, { position: 'topleft' }).addTo(map);

    // --- Variables globales ---
    let puntos = [null, null];
    let markers = [null, null];
    let modoTransporte = null; // Debería ser null al inicio
    let modoSeleccion = null;
    let rutaLine = null;
    let rutaManhattanLine = null;
    let marcadorBusqueda = null;

    // *** VELOCIDADES REALISTAS (en metros por minuto) ***
    const velocidades = {
        auto: 500,    // 30 km/h = 500 metros/minuto
        bici: 250,    // 15 km/h = 250 metros/minuto
        peaton: 67    // 4 km/h = ~67 metros/minuto
    };

    // *** CONSUMO DE COMBUSTIBLE (litros por kilómetro) ***
    const consumoCombustibleLtsKm = 0.1; // Ejemplo: 10 km por litro (0.1 litros por km)

    const infoDiv = document.getElementById('info');
    const selectTransporte = document.getElementById('transporte');

    const btnOrigen = document.getElementById('btnOrigen');
    const btnDestino = document.getElementById('btnDestino');
    const datosPuntosDiv = document.getElementById('datosPuntos');

    // --- Función de inicialización ---
    function initializeApp() {
        selectTransporte.value = "";
        modoTransporte = null;

        btnOrigen.disabled = true;
        btnDestino.disabled = true;

        infoDiv.querySelector('p').textContent = 'Selecciona un modo de transporte antes de elegir puntos.';
    }


    // --- Manejo del modo de transporte ---
    selectTransporte.addEventListener('change', (e) => {
        modoTransporte = e.target.value;

        btnOrigen.disabled = !modoTransporte;
        btnDestino.disabled = !modoTransporte;

        infoDiv.querySelector('p').textContent = modoTransporte ? 'Ahora puedes seleccionar origen o destino. Haz clic en el mapa o busca una dirección.' : 'Selecciona un modo de transporte antes de elegir puntos.';

        modoSeleccion = null;
    });

    // --- Manejo de botones Origen/Destino ---
    btnOrigen.addEventListener('click', () => {
        modoSeleccion = 'origen';
        infoDiv.querySelector('p').textContent = 'Haz clic en el mapa para seleccionar el origen.';
        if (marcadorBusqueda) {
            map.removeLayer(marcadorBusqueda);
            marcadorBusqueda = null;
        }
    });

    btnDestino.addEventListener('click', () => {
        modoSeleccion = 'destino';
        infoDiv.querySelector('p').textContent = 'Haz clic en el mapa para seleccionar el destino.';
        if (marcadorBusqueda) {
            map.removeLayer(marcadorBusqueda);
            marcadorBusqueda = null;
        }
    });

    // --- Función para limpiar rutas y puntos ---
    function limpiarTodo() {
        markers.forEach(m => { if (m) map.removeLayer(m); });
        markers = [null, null];
        puntos = [null, null];

        if (rutaLine) {
            map.removeLayer(rutaLine);
            rutaLine = null;
        }
        if (rutaManhattanLine) {
            map.removeLayer(rutaManhattanLine);
            rutaManhattanLine = null;
        }
        if (marcadorBusqueda) {
            map.removeLayer(marcadorBusqueda);
            marcadorBusqueda = null;
        }

        datosPuntosDiv.innerHTML = "";
        const infoTiempoDiv = document.getElementById('info-tiempo');
        if (infoTiempoDiv) infoTiempoDiv.remove();

        selectTransporte.value = "";
        modoTransporte = null;
        btnOrigen.disabled = true;
        btnDestino.disabled = true;
        modoSeleccion = null;

        infoDiv.querySelector('p').textContent = 'Selecciona un modo de transporte antes de elegir puntos.';

        const existingResetBtn = document.getElementById('btnReset');
        if (existingResetBtn) {
            existingResetBtn.removeEventListener('click', limpiarTodo);
            existingResetBtn.addEventListener('click', limpiarTodo);
        }
    }

    // --- Función para agregar punto (mapa o búsqueda) ---
    function agregarPunto(latlng, tipo, display_name = 'No disponible') {
        let index = (tipo === 'origen') ? 0 : 1;

        if (markers[index]) {
            map.removeLayer(markers[index]);
        }

        puntos[index] = latlng;
        markers[index] = L.marker(latlng, {
            title: tipo.charAt(0).toUpperCase() + tipo.slice(1),
            icon: L.icon({
                iconUrl: (tipo === 'origen' ? 'https://cdn-icons-png.flaticon.com/512/684/684908.png' : 'https://cdn-icons-png.flaticon.com/512/684/684908.png'),
                iconSize: [30, 30],
                iconAnchor: [15, 30],
                popupAnchor: [0, -25]
            })
        }).addTo(map);

        obtenerInfoLugar(latlng, tipo);

        if (puntos[0] && puntos[1] && modoTransporte) {
            calcularRuta();
        }
    }

    // --- Obtener información detallada del lugar (Nominatim Reverse Geocoding) ---
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
            .catch(() => {
                console.error('Error al obtener información del lugar.');
                let existingDiv = document.getElementById(`info-${tipo}`);
                if (existingDiv) {
                    existingDiv.innerHTML = `<h4>${tipo === 'origen' ? 'Origen' : 'Destino'}</h4><p>Información no disponible.</p>`;
                } else {
                    const div = document.createElement('div');
                    div.id = `info-${tipo}`;
                    div.style.marginBottom = '1em';
                    div.innerHTML = `<h4>${tipo === 'origen' ? 'Origen' : 'Destino'}</h4><p>Información no disponible.</p>`;
                    datosPuntosDiv.appendChild(div);
                }
            });
    }

    // --- Función que llama al backend y dibuja ambas rutas ---
    function calcularRuta() {
        if (!puntos[0] || !puntos[1]) {
            console.warn("Faltan puntos para calcular la ruta.");
            return;
        }
        if (!modoTransporte) {
            alert("Por favor, selecciona un modo de transporte.");
            return;
        }

        fetch('/ruta', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                origen: { lat: puntos[0].lat, lng: puntos[0].lng },
                destino: { lat: puntos[1].lat, lng: puntos[1].lng },
                modo: 'manhattan' // O el modo de ruteo que estés usando en el backend
            })
        })
        .then(res => res.json())
        .then(data => {
            if (data.error) {
                alert("Error al calcular la ruta: " + data.error);
                if (rutaLine) map.removeLayer(rutaLine);
                if (rutaManhattanLine) map.removeLayer(rutaManhattanLine);
                rutaLine = null;
                rutaManhattanLine = null;
                return;
            }

            const { ruta, distancia_metros, ruta_manhattan, mensaje_manhattan } = data;

            if (rutaLine) {
                map.removeLayer(rutaLine);
            }
            if (rutaManhattanLine) {
                map.removeLayer(rutaManhattanLine);
            }

            rutaLine = L.polyline(ruta, { color: 'blue', weight: 5 }).addTo(map);

            if (ruta_manhattan && ruta_manhattan.length > 0) {
                rutaManhattanLine = L.polyline(ruta_manhattan, { color: 'red', weight: 4, dashArray: '6,6' }).addTo(map);
            } else {
                rutaManhattanLine = null;
            }

            const grupoRutas = new L.featureGroup([rutaLine]);
            if (rutaManhattanLine) grupoRutas.addLayer(rutaManhattanLine);
            if (markers[0]) grupoRutas.addLayer(markers[0]);
            if (markers[1]) grupoRutas.addLayer(markers[1]);

            if (grupoRutas.getLayers().length > 0) {
                map.fitBounds(grupoRutas.getBounds(), { padding: [50, 50] });
            }

            const velocidadActual = velocidades[modoTransporte] || velocidades.auto; // metros/minuto
            const tiempo_minutos = (distancia_metros / velocidadActual).toFixed(1); // minutos

            // Convertir la velocidad de metros/minuto a km/h para mostrarla
            const velocidad_kmh = (velocidadActual * 60 / 1000).toFixed(1); // (metros/minuto * 60 minutos/hora) / 1000 metros/km

            let consumoCombustibleHTML = '';
            if (modoTransporte === 'auto') {
                const distancia_km = (distancia_metros / 1000); // Distancia en kilómetros
                const consumoLitros = (distancia_km * consumoCombustibleLtsKm).toFixed(2); // Litros
                consumoCombustibleHTML = `<p><strong>Consumo de Combustible:</strong> ${consumoLitros} litros</p>`;
            }

            const infoTiempoHTML = `
                <p><strong>Distancia:</strong> ${(distancia_metros / 1000).toFixed(2)} km</p>
                <p><strong>Tiempo estimado (${modoTransporte}):</strong> ${tiempo_minutos} minutos</p>
                <p><strong>Velocidad (${modoTransporte}):</strong> ${velocidad_kmh} km/h</p>
                ${consumoCombustibleHTML}
                ${mensaje_manhattan ? `<p style="color:white;"><strong>Manhattan:</strong> ${mensaje_manhattan}</p>` : ''}
                <button id="btnReset" class="btn-reset">Nueva búsqueda</button>
            `;

            let infoTiempoDiv = document.getElementById('info-tiempo');
            if (!infoTiempoDiv) {
                infoTiempoDiv = document.createElement('div');
                infoTiempoDiv.id = 'info-tiempo';
                infoDiv.appendChild(infoTiempoDiv);
            }
            infoTiempoDiv.innerHTML = infoTiempoHTML;

            const btnReset = document.getElementById('btnReset');
            if (btnReset) {
                btnReset.removeEventListener('click', limpiarTodo);
                btnReset.addEventListener('click', limpiarTodo);
            }
        })
        .catch(error => {
            console.error("Error en fetch de ruta:", error);
            alert("Error al calcular la ruta. Verifica la conexión o los puntos seleccionados.");
        });
    }

    // --- Click en mapa para elegir puntos ---
    map.on('click', e => {
        if (!modoTransporte) {
            alert('Primero selecciona un modo de transporte.');
            return;
        }
        if (!modoSeleccion) {
            alert('Primero selecciona si vas a elegir origen o destino (botones).');
            return;
        }

        if (marcadorBusqueda) {
            map.removeLayer(marcadorBusqueda);
            marcadorBusqueda = null;
        }

        agregarPunto(e.latlng, modoSeleccion);
        modoSeleccion = null;
        infoDiv.querySelector('p').textContent = 'Puntos seleccionados. Si deseas cambiar, haz clic en los botones de Origen/Destino.';
    });

    // --- Configuración de la barra de búsqueda (Leaflet GeoSearch) ---
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
        const displayName = result.location.label;

        if (marcadorBusqueda) {
            map.removeLayer(marcadorBusqueda);
        }

        marcadorBusqueda = L.marker(latlng, {
            icon: L.icon({
                iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
                iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
                shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
                iconSize: [25, 41],
                iconAnchor: [12, 41],
                popupAnchor: [1, -34],
                shadowSize: [41, 41]
            })
        }).addTo(map);

        marcadorBusqueda
            .bindPopup(`<strong>Resultado de búsqueda:</strong><br>${displayName}`)
            .openPopup();

        map.setView(latlng, 16);

        searchControl.clear();
    });

    map.on('popupclose', (e) => {
        if (e.popup && e.popup._source === marcadorBusqueda) {
            map.removeLayer(marcadorBusqueda);
            marcadorBusqueda = null;
        }
    });

    // Llama a la función de inicialización al cargar el DOM
    initializeApp();

});