# Personalidad Gerstep completa

`personality.py` carga siempre `SKILL_RUNTIME.md`: los trece apartados de la skill V2 original, incluidos sus diez mecanismos de reacción, registro de confianza, gramática, ritmo, vocabulario, actuación, ejemplos y límites de realidad. No carga `SYSTEM_PROMPT_MINI.txt`.

La adaptación conserva las reglas originales y anonimiza las referencias a integrantes de conversaciones privadas. Omite el inventario de archivos personales y cambia la recomendación anterior de usar un prompt mini por la instrucción actual del streamer de mantener la skill completa. Las reglas de integración son responsabilidades del backend, no permisos para ejecutar herramientas.

`VOICE_REFERENCE.md`, `COMEDY_REFERENCE.md` y `EXAMPLES.md` contienen extractos originales de los documentos de estilo de `gerstep-ai-skill`. El loader selecciona apartados según la intención del turno, sin solicitudes adicionales de IA. Los ejemplos son ficticios y enseñan mecanismos; no deben convertirse en preguntas, antecedentes ni hechos del turno actual. Ninguno de estos archivos contiene exportaciones de WhatsApp, credenciales o incidentes privados.

El prompt completo de personalidad ronda 30–32 mil caracteres y 10–11 mil tokens según la estimación conservadora UTF-8/3. El consumo real lo informa el proveedor. El constructor debe reservar este coste antes de añadir memoria opcional y no recortar la skill silenciosamente. Cambiar esta configuración aumenta el consumo frente al mini anterior; no garantiza por sí solo la calidad del humor o la ausencia de errores del modelo.

Los cuatro recursos permitidos se leen una vez y se mantienen en caché. La ruta se fija junto al módulo: los espectadores no pueden seleccionar archivos. `personality_metadata(job)` muestra versión, intención, recursos, tamaño y huella del prompt sin devolver su texto.
