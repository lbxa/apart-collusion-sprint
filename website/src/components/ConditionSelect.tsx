import { useEffect, useRef, useState } from "react";
import { Field, FieldLabel } from "@/components/ui/field";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export default function ConditionSelect({ items }: { items: { id: string; label: string }[] }) {
  const field = useRef<HTMLDivElement>(null);
  const [hydrated, setHydrated] = useState(false);
  useEffect(() => setHydrated(true), []);
  return (
    <Field ref={field} hidden={!hydrated} orientation="horizontal" className="my-5 flex-wrap gap-3">
      <FieldLabel id="condition-label" htmlFor="condition">Study condition</FieldLabel>
      <Select items={items.map(item => ({ value: item.id, label: item.label }))} defaultValue="primary" onValueChange={value => {
        const chart = field.current?.closest<HTMLElement>("[data-confirmation]");
        if (!chart || typeof value !== "string") return;
        chart.dataset.condition = value;
        chart.dispatchEvent(new Event("condition-change"));
      }}>
        <SelectTrigger id="condition" aria-labelledby="condition-label" className="w-76 max-w-full">
          <SelectValue />
        </SelectTrigger>
        <SelectContent><SelectGroup>{items.map(item => <SelectItem key={item.id} value={item.id}>{item.label}</SelectItem>)}</SelectGroup></SelectContent>
      </Select>
    </Field>
  );
}
