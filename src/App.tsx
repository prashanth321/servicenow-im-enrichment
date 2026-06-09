import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import ForgotPasswordPage from "./ForgotPasswordPage";
import LoginPage from "./LoginPage";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/login" replace />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      </Routes>
    </BrowserRouter>
  );
}
