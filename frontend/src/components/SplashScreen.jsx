import logo from '../assets/weblinx_logo.svg';

export default function SplashScreen() {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-gray-50">
      <div className="flex flex-col items-center gap-4 animate-pulse">
        <img src={logo} alt="Weblinx Outreach OS" className="h-16 w-16" />
        <div className="text-center">
          <h1 className="text-xl font-bold text-gray-900 tracking-tight">Weblinx Outreach OS</h1>
          <p className="text-xs text-gray-500 font-medium">Loading sales platform...</p>
        </div>
      </div>
    </div>
  );
}
