# Publicación controlada de Big Asere AI en GitHub

## Antes de publicar
- Este paquete contiene SOLO el código del asistente local. No lo mezcles con otros repositorios ni agregues conversaciones personales.
- La compilación con Xcode 26.2 y una respuesta real de Ollama se comprobaron en un Mac; las otras herramientas necesitan más validación manual.
- La licencia MIT ya está elegida. La publicación pública requiere una revisión final de seguridad y autorización expresa. Ver `LICENSE_DECISION.md`.
- Mantén el repositorio privado durante la revisión inicial.

## Método visual con GitHub Desktop (sin Terminal)
1. Descarga GitHub Desktop desde https://desktop.github.com/ e inicia sesión en tu cuenta GitHub.
2. Descomprime este ZIP y conserva la carpeta de código en **Documentos** u otra ubicación estable de tu Mac.
3. En GitHub Desktop: **File → Add Local Repository… → Choose…** y selecciona esa carpeta.
4. Si la app te informa que todavía no es un repositorio, pulsa **Create a repository here** y confirma. No elijas ningún repositorio existente de Big Asere FOOD, SHOP o SERVICES.
5. Revisa la pestaña **Changes** y confirma que no aparecen credenciales ni archivos personales. Haz el primer commit si la app lo solicita.
6. Haz clic en **Publish repository**. Sugiero el nombre `big-asere-ai-local`. Deja activada la opción **Keep this code private**.
7. Revisa el repositorio privado en GitHub, el README, las pruebas de Actions y el documento `SECURITY.md`.
8. Si estás conforme con seguridad y licencia, decide explícitamente si deseas hacerlo **Public**. No cambiaremos la visibilidad antes de tu aprobación.

Guía oficial GitHub Desktop: https://docs.github.com/en/desktop/adding-and-cloning-repositories/adding-an-existing-project-to-github-using-github-desktop

## NO hacer
- No subir el archivo `state.json`, capturas con información personal ni carpetas del repositorio de Big Asere.
- No incluir una versión `.app` alegando que es una instalación firmada por Apple.
- No activar acciones automáticas para desplegar ni modificar producción.
