import { Component, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";

export class WorkspaceBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <main className="min-h-screen flex items-center justify-center p-6">
        <Card className="w-full max-w-md">
          <CardHeader>
            <CardTitle>The workspace couldn’t load</CardTitle>
            <CardDescription>
              A workspace update or connection interruption may have caused
              this. Reload to open the current version. Saved clinic records
              remain in the backend.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex gap-3">
            <Button onClick={() => window.location.reload()}>
              Reload workspace
            </Button>
            <Button
              variant="outline"
              onClick={() => window.location.assign("/staff/appointments")}
            >
              Open appointments
            </Button>
          </CardContent>
        </Card>
      </main>
    );
  }
}
