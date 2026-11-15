"use client";

import { Plus, Trash2 } from "lucide-react";
import { parseList, titleCase } from "@/lib/format";
import type { JsonSchema } from "@/lib/types";
import { Button, Checkbox, Field, Input, Select } from "./ui";

/**
 * Renders a parameter form from the JSON schema that the backend publishes for each change operation.
 * Supports booleans, numbers, strings (with enums / secrets), lists of scalars and lists of objects.
 * The backend validates again before anything is executed.
 */

export type Values = Record<string, unknown>;

export function resolve(s: JsonSchema, root: JsonSchema): JsonSchema {
  if (s.$ref) {
    const name = s.$ref.split("/").pop() || "";
    return { ...(root.$defs?.[name] || {}), title: s.title || root.$defs?.[name]?.title };
  }
  return s;
}

/** Unwrap Optional[X] (anyOf [X, null]) into X plus a nullable flag. */
export function unwrap(s: JsonSchema, root: JsonSchema): { schema: JsonSchema; nullable: boolean } {
  if (s.anyOf) {
    const nonNull = s.anyOf.filter((x) => x.type !== "null");
    const nullable = nonNull.length !== s.anyOf.length;
    const base = resolve(nonNull[0] || {}, root);
    return { schema: { ...base, title: s.title, default: s.default, enum: base.enum || s.enum }, nullable };
  }
  return { schema: resolve(s, root), nullable: false };
}

export function defaultsFor(schema: JsonSchema): Values {
  const out: Values = {};
  for (const [k, raw] of Object.entries(schema.properties || {})) {
    const { schema: s, nullable } = unwrap(raw, schema);
    if (raw.default !== undefined) out[k] = raw.default;
    else if (s.type === "array") out[k] = [];
    else if (s.type === "boolean" && !nullable) out[k] = false;
    else if (nullable) out[k] = null;
  }
  return out;
}

function isSecret(name: string, s: JsonSchema): boolean {
  return s.format === "password" || s.writeOnly === true || /password|secret|key$/i.test(name);
}

function label(name: string, s: JsonSchema): string {
  return (s.title || titleCase(name)).replace(/\bVlan\b/g, "VLAN").replace(/\bVlans\b/g, "VLANs").replace(/\bW\b/, "(W)").replace(/\bPoe\b/, "PoE").replace(/\bBpdu\b/, "BPDU");
}

function ScalarInput({
  name,
  schema,
  nullable,
  value,
  onChange,
}: {
  name: string;
  schema: JsonSchema;
  nullable: boolean;
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  const id = `f-${name}`;
  if (schema.enum) {
    return (
      <Select id={id} value={value === null || value === undefined ? "" : String(value)} onChange={(e) => onChange(e.target.value === "" ? null : e.target.value)}>
        {(nullable || value === undefined || value === null) && <option value="">{nullable ? "— leave unchanged —" : "Select…"}</option>}
        {schema.enum.map((o) => (
          <option key={String(o)} value={String(o)}>
            {String(o)}
          </option>
        ))}
      </Select>
    );
  }
  if (schema.type === "boolean") {
    if (nullable) {
      return (
        <Select id={id} value={value === null || value === undefined ? "" : value ? "true" : "false"} onChange={(e) => onChange(e.target.value === "" ? null : e.target.value === "true")}>
          <option value="">— leave unchanged —</option>
          <option value="true">Yes</option>
          <option value="false">No</option>
        </Select>
      );
    }
    return <Checkbox label={value ? "Yes" : "No"} checked={Boolean(value)} onChange={onChange} />;
  }
  if (schema.type === "integer" || schema.type === "number") {
    return (
      <Input
        id={id}
        type="number"
        min={schema.minimum}
        max={schema.maximum}
        step={schema.type === "integer" ? 1 : "any"}
        value={value === null || value === undefined ? "" : String(value)}
        placeholder={nullable ? "leave unchanged" : undefined}
        onChange={(e) => {
          const v = e.target.value;
          onChange(v === "" ? (nullable ? null : undefined) : schema.type === "integer" ? parseInt(v, 10) : parseFloat(v));
        }}
      />
    );
  }
  return (
    <Input
      id={id}
      type={isSecret(name, schema) ? "password" : "text"}
      autoComplete={isSecret(name, schema) ? "new-password" : "off"}
      maxLength={schema.maxLength}
      value={value === null || value === undefined ? "" : String(value)}
      placeholder={nullable ? "leave unchanged" : undefined}
      onChange={(e) => onChange(e.target.value === "" && nullable ? null : e.target.value)}
    />
  );
}

function ListInput({ name, schema, value, onChange }: { name: string; schema: JsonSchema; value: unknown; onChange: (v: unknown) => void }) {
  const itemType = schema.items?.type;
  const arr = Array.isArray(value) ? value : [];
  const text = arr.join(", ");
  return (
    <Input
      id={`f-${name}`}
      defaultValue={text}
      key={text}
      placeholder={/port/i.test(name) ? "e.g. 1-4, 7, 25" : "comma separated"}
      onBlur={(e) => {
        const items = parseList(e.target.value);
        onChange(itemType === "integer" ? items.map((x) => parseInt(x, 10)).filter((x) => !Number.isNaN(x)) : items);
      }}
    />
  );
}

function ObjectListInput({
  name,
  item,
  value,
  onChange,
}: {
  name: string;
  item: JsonSchema;
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  const rows = (Array.isArray(value) ? value : []) as Values[];
  const props = Object.entries(item.properties || {});
  return (
    <div className="space-y-2">
      {rows.map((row, i) => (
        <div key={i} className="flex flex-wrap items-end gap-2 rounded border border-line p-2">
          {props.map(([k, ps]) => (
            <div key={k} className="min-w-32 flex-1">
              <Field label={label(k, ps)} htmlFor={`f-${name}-${i}-${k}`}>
                <ScalarInput
                  name={`${name}-${i}-${k}`}
                  schema={ps}
                  nullable={false}
                  value={row[k]}
                  onChange={(v) => onChange(rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)))}
                />
              </Field>
            </div>
          ))}
          <Button size="sm" variant="ghost" aria-label="Remove row" onClick={() => onChange(rows.filter((_, j) => j !== i))}>
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      ))}
      <Button size="sm" onClick={() => onChange([...rows, Object.fromEntries(props.map(([k]) => [k, ""]))])}>
        <Plus className="h-4 w-4" /> Add row
      </Button>
    </div>
  );
}

export function SchemaForm({
  schema,
  values,
  onChange,
  hidden = [],
}: {
  schema: JsonSchema;
  values: Values;
  onChange: (v: Values) => void;
  hidden?: string[];
}) {
  const required = new Set(schema.required || []);
  const entries = Object.entries(schema.properties || {}).filter(([k]) => !hidden.includes(k));
  if (!entries.length) return <p className="text-sm text-muted">This operation has no parameters.</p>;
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      {entries.map(([name, raw]) => {
        const { schema: s, nullable } = unwrap(raw, schema);
        const set = (v: unknown) => onChange({ ...values, [name]: v });
        const lab = label(name, s) + (required.has(name) ? " *" : "");
        let control: React.ReactNode;
        if (s.type === "array") {
          const item = s.items ? resolve(s.items, schema) : {};
          control = item.type === "object" || item.properties ? (
            <ObjectListInput name={name} item={item} value={values[name]} onChange={set} />
          ) : (
            <ListInput name={name} schema={s} value={values[name]} onChange={set} />
          );
        } else {
          control = <ScalarInput name={name} schema={s} nullable={nullable} value={values[name]} onChange={set} />;
        }
        const wide = s.type === "array" && (s.items?.$ref || s.items?.type === "object");
        return (
          <div key={name} className={wide ? "sm:col-span-2" : undefined}>
            <Field label={lab} htmlFor={`f-${name}`} hint={s.description}>
              {control}
            </Field>
          </div>
        );
      })}
    </div>
  );
}
