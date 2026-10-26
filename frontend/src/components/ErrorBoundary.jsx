import React from 'react';
import { RiAlertLine, RiRefreshLine, RiHome5Line } from 'react-icons/ri';
import { Button } from './ui/Button';

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    this.setState({ errorInfo });
    console.error('ErrorBoundary caught an unhandled React error:', error, errorInfo);
  }

  handleReload = () => {
    window.location.reload();
  };

  handleReset = () => {
    this.setState({ hasError: false, error: null, errorInfo: null });
    if (this.props.onReset) {
      this.props.onReset();
    }
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback({
          error: this.state.error,
          reset: this.handleReset,
        });
      }

      return (
        <div className="min-h-[300px] flex-1 flex items-center justify-center p-6">
          <div className="w-full max-w-lg bg-white dark:bg-slate-900 rounded-2xl border border-rose-200 dark:border-rose-900/60 p-6 shadow-xl text-center space-y-4">
            <div className="w-12 h-12 mx-auto rounded-full bg-rose-100 dark:bg-rose-950/60 text-rose-600 dark:text-rose-400 flex items-center justify-center">
              <RiAlertLine size={26} />
            </div>

            <div>
              <h2 className="text-lg font-bold text-slate-900 dark:text-white">
                {this.props.title || 'Something went wrong on this screen'}
              </h2>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                {this.props.description || 'An unexpected rendering error occurred. Your data is safe.'}
              </p>
            </div>

            {this.state.error && (
              <div className="p-3 bg-rose-50/50 dark:bg-rose-950/30 border border-rose-200 dark:border-rose-900/50 rounded-lg text-left overflow-x-auto max-h-36">
                <p className="text-xs font-mono text-rose-700 dark:text-rose-300 font-semibold">
                  {this.state.error.name}: {this.state.error.message}
                </p>
              </div>
            )}

            <div className="flex items-center justify-center gap-3 pt-2">
              <Button
                variant="outline"
                size="sm"
                onClick={this.handleReset}
                className="flex items-center gap-1.5 text-xs"
              >
                Try Again
              </Button>
              <Button
                variant="primary"
                size="sm"
                onClick={this.handleReload}
                className="bg-teal-600 hover:bg-teal-700 text-white flex items-center gap-1.5 text-xs shadow-sm"
              >
                <RiRefreshLine size={14} /> Reload Page
              </Button>
              <Button
                as="a"
                href="/"
                variant="ghost"
                size="sm"
                className="flex items-center gap-1.5 text-xs"
              >
                <RiHome5Line size={14} /> Dashboard
              </Button>
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
