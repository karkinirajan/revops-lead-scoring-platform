import { SimulateForm } from "@/components/simulate/SimulateForm";

export default function SimulatePage() {
  return (
    <div className="p-4 sm:p-8 max-w-3xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold" style={{ color: "var(--text)" }}>Score Simulator</h1>
        <p className="text-sm mt-0.5" style={{ color: "var(--text-muted)" }}>
          What-if analysis — enter a feature vector to see the score without persisting
        </p>
      </div>
      <SimulateForm />
    </div>
  );
}
