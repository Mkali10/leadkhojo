import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/Feedback";

export function NotFoundPage() {
  const navigate = useNavigate();
  return (
    <div className="card">
      <EmptyState
        title="Page not found"
        description="That link does not point anywhere in this app. A deleted scan will do this too."
        action={
          <Button variant="primary" onClick={() => navigate("/")}>
            Back to the dashboard
          </Button>
        }
      />
    </div>
  );
}
