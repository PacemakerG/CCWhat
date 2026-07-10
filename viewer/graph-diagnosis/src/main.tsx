import { createRoot, type Root } from 'react-dom/client';

import { GraphDiagnosisApp } from './GraphDiagnosisApp';
import type { GraphDiagnosisContext } from './types';
import './styles.css';

let root: Root | undefined;
let mountElement: HTMLElement | undefined;
let currentContext: GraphDiagnosisContext | undefined;

function render(context: GraphDiagnosisContext) {
  if (!root || !mountElement) return;
  currentContext = context;
  root.render(<GraphDiagnosisApp context={context} />);
}

window.CCWhatGraphDiagnosis = {
  mount(element: HTMLElement, context: GraphDiagnosisContext) {
    if (mountElement !== element) {
      root?.unmount();
      mountElement = element;
      root = createRoot(element);
    }
    render(context);
  },
  updateContext(context: Partial<GraphDiagnosisContext>) {
    if (currentContext) render({ ...currentContext, ...context });
  },
  unmount() {
    root?.unmount();
    root = undefined;
    mountElement = undefined;
    currentContext = undefined;
  },
};

declare global {
  interface Window {
    CCWhatGraphDiagnosis: {
      mount: (element: HTMLElement, context: GraphDiagnosisContext) => void;
      updateContext: (context: Partial<GraphDiagnosisContext>) => void;
      unmount: () => void;
    };
  }
}
