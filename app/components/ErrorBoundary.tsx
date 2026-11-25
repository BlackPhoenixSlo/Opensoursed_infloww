"use client";


import { Component, type ErrorInfo, type ReactNode } from "react";

import { reportError } from "@/lib/errorReporter";

interface Props {
  children: ReactNode;
  scope?: string;
}

interface State {
  err: Error | null;
}

// class: hooks have no componentDidCatch / getDerivedStateFromError
export class ErrorBoundary extends Component<Props, State> {
  state: State = { err: null };

  static getDerivedStateFromError(err: Error): State {
    return { err };
  }

  componentDidCatch(err: Error, info: ErrorInfo): void {
    reportError(err, "react-render", {
      scope: this.props.scope ?? "root",
      componentStack: info.componentStack ?? null,
    });
  }

  private reset = () => this.setState({ err: null });

  render(): ReactNode {
    if (!this.state.err) return this.props.children;
    return (
      <div className="min-h-[50vh] grid place-items-center p-6">
        <div className="max-w-md text-center space-y-3 bg-panel border border-border rounded-lg p-6 shadow-xl">
          <div className="text-base font-semibold text-err">Something broke.</div>
          <div className="text-xs text-fg-dim">
            The error has been recorded to <span className="font-mono">/admin/errors</span>.
            Try the button below; if it keeps happening, refresh the tab.
          </div>
          <pre className="text-[10px] text-left bg-bg-elev-1 border border-border rounded-md p-2 overflow-auto max-h-40">
            {this.state.err.message}
          </pre>
          <button
            type="button"
            onClick={this.reset}
            className="text-xs bg-accent text-white px-3 py-1.5 rounded-md hover:opacity-90"
          >
            Try again
          </button>
        </div>
      </div>
    );
  }
}
