import { redirect } from "next/navigation";

export default function InternalHome() {
  redirect("/internal/metrics");
}
