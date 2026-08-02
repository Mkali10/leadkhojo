import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * Catches render-time faults so one bad component does not blank the page.
 *
 * A white screen tells the user nothing and loses whatever they were doing.
 * This keeps the shell, states what happened, and offers a way out.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // The browser console is the only sink available here; there is no
    // telemetry endpoint in this build and inventing one would be a
    // surprising thing for a local tool to do.
    console.error("Unhandled render error", error, info.componentStack);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <div className="mx-auto max-w-lg px-4 py-20 text-center">
        <h1 className="text-lg font-semibold text-ink-900">Something broke while rendering</h1>
        <p className="mt-2 text-sm text-ink-600">
          This is a bug in the interface, not in your data — nothing that has been scanned is
          affected.
        </p>
        <pre className="scroll-x mt-4 rounded-lg bg-ink-100 p-3 text-left font-mono text-xs text-ink-700">
          {error.message}
        </pre>
        <div className="mt-5 flex justify-center gap-2">
          <button
            type="button"
            onClick={() => this.setState({ error: null })}
            className="rounded-lg border border-ink-200 bg-white px-4 py-2 text-sm font-medium text-ink-800 hover:bg-ink-50"
          >
            Try again
          </button>
          <button
            type="button"
            onClick={() => window.location.assign("/")}
            className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
          >
            Back to the dashboard
          </button>
        </div>
      </div>
    );
  }
}
