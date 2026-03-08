import { Bot } from "lucide-react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { PresetResponse } from "@/api/types";

interface PresetSelectorProps {
  presets: PresetResponse[];
  selected: string | null;
  onChange: (presetId: string | null) => void;
  disabled?: boolean;
}

const AUTO_VALUE = "__auto__";

export default function PresetSelector({
  presets,
  selected,
  onChange,
  disabled,
}: PresetSelectorProps) {
  if (presets.length === 0) return null;

  const defaultPreset = presets.find((p) => p.is_default);
  const autoLabel = defaultPreset ? `Default (${defaultPreset.name})` : "Default";

  return (
    <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
      <Bot className="h-3.5 w-3.5 shrink-0" />
      <Select
        value={selected ?? AUTO_VALUE}
        onValueChange={(v) => onChange(v === AUTO_VALUE ? null : v)}
        disabled={disabled}
      >
        <SelectTrigger
          size="sm"
          className="h-7 border-none bg-transparent shadow-none px-1.5 text-xs text-muted-foreground hover:text-foreground"
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={AUTO_VALUE}>{autoLabel}</SelectItem>
          {presets.map((p) => (
            <SelectItem key={p.preset_id} value={p.preset_id}>
              {p.name}
              {p.is_default ? " *" : ""}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
