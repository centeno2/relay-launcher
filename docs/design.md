# Relay

## Dirección actual: biblioteca inmersiva

Referencia: Horizon instalado y su implementación pública `glass_home.rs`.
Se toman la navegación superior, los grupos de acciones y el espacio para el
juego. Relay conserva su ventana nativa y la paleta del escritorio.

- Color: grafito `#202329`, metal `#30353D`, blanco `#F5F6F7`, gris
  `#BAC1CB`, ámbar BO2 `#F5A34D`, azul noche `#15232F`.
- Tipo: fuente del escritorio para controles; sans condensada para BO2.
- Composición: navegación horizontal; escenario panorámico ancho; título y
  acción a la izquierda; tres fotografías seleccionables debajo; una barra
  compacta para carpeta, Drive y servidores. Todo alineado a la izquierda.
- Profundidad: perspectiva en las fotografías y parallax suave del escenario
  al mover el cursor. Sin bucle de animación en reposo; opción de reducir
  movimiento y respeto por las animaciones desactivadas del escritorio.
- Arte: imágenes reales de BO2 Zombies, con procedencia documentada, sin IA.

```text
Relay       Biblioteca  Servidores  Actividad  Configuración
┌──────────────────────────────────────────────────────────┐
│ CALL OF DUTY                                             │
│ BLACK OPS II             escena real de Zombies          │
│ ZOMBIES                                                  │
│ [Jugar Zombies] [ajustes]                  ambiente       │
│ estado real                                              │
└──────────────────────────────────────────────────────────┘
Ambientes                         Cambiar imagen / Créditos
[ fotografía ]    [ fotografía ]    [ fotografía ]
Carpeta del juego      Drive              Explorar servidores
```

Revisión previa: se retiran la barra lateral y las dos tarjetas de texto que
reducían la escena a un banner pequeño. La galería identifica lugares reales
y cambia solo el fondo: no promete seleccionar mapas ni instalar DLC.
Los efectos siguen el gesto del usuario y mantienen quietos texto y botones.
El resto de la aplicación permanece sobrio para concentrar el carácter en BO2.

## Revisión del resultado

Se revisaron capturas en 1180 × 790 y 760 × 560, en claro y oscuro. El fondo
conserva al zombi y el autobús de TranZit; la sombra se limita al texto. Los
botones mantienen su posición mientras el fondo responde al cursor. En
ventanas bajas se oculta la frase secundaria y se reduce la galería.

La perspectiva es una transformación 3D de las fotografías, no un modelo
tridimensional del juego. Solo se anima durante una interacción; las imágenes
del escenario se escalan al cambiar de tamaño y se reutilizan en cada cuadro.

Referencia de estructura: [Horizon, glass_home.rs](https://github.com/horizon-rust/horizon/blob/main/launcher/src/glass_home.rs).
Fotografías y procedencia: [ARTWORK.md](ARTWORK.md).
