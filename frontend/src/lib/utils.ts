import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function debounce<T extends (...args: any[]) => any>(
  func: T,
  wait: number
): (...args: Parameters<T>) => void {
  let timeout: ReturnType<typeof setTimeout> | null = null;
  return (...args: Parameters<T>) => {
    if (timeout) clearTimeout(timeout);
    timeout = setTimeout(() => func(...args), wait);
  };
}

export function generateAlias(tableName: string, existingAliases: string[]): string {
  const base = tableName.substring(0, 2).toLowerCase();
  const aliasSet = new Set(existingAliases);
  if (!aliasSet.has(base)) {
    return base;
  }
  let counter = 2;
  while (aliasSet.has(`${base}${counter}`)) {
    counter++;
  }
  return `${base}${counter}`;
}

export function generateNodeId(): string {
  return `node-${Date.now()}-${Math.random().toString(36).substring(2, 8)}`;
}

export function generateJoinId(): string {
  return `join-${Date.now()}-${Math.random().toString(36).substring(2, 8)}`;
}
