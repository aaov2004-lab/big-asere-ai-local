# Security & privacy / Seguridad y privacidad

This project is **experimental**; no third-party security audit has been completed.
Este proyecto es **experimental** y no ha recibido una auditoría independiente.

## Precauciones para usuarios

- Descarga código únicamente de fuentes de confianza y **revísalo antes de compilarlo**.
- El backend Python escucha en el loopback `127.0.0.1` y exige una cookie de sesión privada; eso reduce riesgos, **no garantiza seguridad absoluta**.
- La sesión es creada al iniciar el proceso; la carga inicial utiliza un token temporal en una URL local.
- La integración **App Sandbox está desactivada** en el proyecto actual. Es una limitación de seguridad pendiente de revisión.
- La selección de carpetas solicita intervención del usuario, pero no implica que todos los archivos dentro estén libres de credenciales.
- El filtro de archivos y la ocultación parcial de secretos son **preventivos, no infalibles**.
- Archivos y contenido Git son datos no confiables: evita seguir instrucciones incrustadas en documentos sin validación.
- Requiere `Python 3` en una ruta esperada del sistema; para distribución pública debe revisarse esta dependencia.
- No publiques ni adjuntes `~/Library/Application Support/Big Asere AI`, `state.json`, modelos privados ni repositorios de otros proyectos.
- No publiques `.app` sin revisar la firma y el proceso de distribución de Apple.

## Alcance actualmente permitido

- Consulta de archivos seleccionados y estado Git, sin operaciones automáticas de escritura en repositorios.
- Chat con el servicio Ollama local; no se habilitan por defecto servicios en la nube.

## Notas para mantenedores

Before public release: audit WKWebView origin rules; session token lifecycle; file authorization; Python subprocess boundaries; Git configuration handling; request size/timeouts; model-origin controls; data retention; accessibility; and license/branding rights. Review `BigAsereAI.xcodeproj/project.pbxproj` before changing signing or sandbox settings. Add regression tests for all changes.

If a vulnerability is discovered, **do not post secrets or exploit details in a public issue**. Contact the project owner through GitHub privately when a contact method is available.
