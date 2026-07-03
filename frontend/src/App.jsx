import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import { useAuth } from "./auth";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Packages from "./pages/Packages";
import Machines from "./pages/Machines";
import Deployments from "./pages/Deployments";
import DeploymentDetail from "./pages/DeploymentDetail";
import Credentials from "./pages/Credentials";
import Users from "./pages/Users";

export default function App() {
  const { user, loading } = useAuth();

  if (loading) return <div className="login-wrap">Đang tải…</div>;
  if (!user) return <Login />;

  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/packages" element={<Packages />} />
        <Route path="/machines" element={<Machines />} />
        <Route path="/deployments" element={<Deployments />} />
        <Route path="/deployments/:id" element={<DeploymentDetail />} />
        <Route path="/credentials" element={<Credentials />} />
        <Route path="/users" element={<Users />} />
        <Route path="*" element={<Navigate to="/" />} />
      </Routes>
    </Layout>
  );
}
