// Tipos mínimos do cliente VNC (@novnc/novnc não publica os seus): só o que a página Computadores usa.
declare module "@novnc/novnc" {
  export default class RFB extends EventTarget {
    constructor(target: HTMLElement, url: string, options?: { wsProtocols?: string[] });
    viewOnly: boolean;
    scaleViewport: boolean;
    resizeSession: boolean;
    focusOnClick: boolean;
    disconnect(): void;
    focus(): void;
  }
}
