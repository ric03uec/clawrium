import { describe, expect, it } from "vitest";

import { OpenAiIcon } from "@/components/icons/openai";

import {
  AMD_BRAND,
  NVIDIA_BRAND,
  getAcceleratorBadge,
  getProviderBrand,
  isNvidiaLocalInference,
} from "./provider-brands";

describe("getProviderBrand", () => {
  it("returns the known brand for ollama with isLocal=true", () => {
    const brand = getProviderBrand("ollama");
    expect(brand.label).toBe("Ollama");
    expect(brand.accentColor).toBe("#808080");
    expect(brand.isLocal).toBe(true);
  });

  it("returns the AWS Bedrock brand for bedrock", () => {
    const brand = getProviderBrand("bedrock");
    expect(brand.label).toBe("AWS Bedrock");
    expect(brand.accentColor).toBe("#FF9900");
    expect(brand.isLocal).toBe(false);
  });

  it("returns the OpenCode brand entry with the OpenAI icon", () => {
    const brand = getProviderBrand("opencode");
    expect(brand.label).toBe("OpenCode");
    expect(brand.Icon).toBe(OpenAiIcon);
    expect(brand.accentColor).toBe("#0F766E");
    expect(brand.isLocal).toBe(false);
  });

  it("returns a generic 'Provider' fallback for null providerType", () => {
    const brand = getProviderBrand(null);
    expect(brand.label).toBe("Provider");
    expect(brand.isLocal).toBe(false);
  });

  it("returns a label-as-providerType fallback for unknown strings", () => {
    const brand = getProviderBrand("totally-unknown");
    expect(brand.label).toBe("totally-unknown");
    expect(brand.isLocal).toBe(false);
  });

  it("does not throw and does not return a prototype value for '__proto__'", () => {
    expect(() => getProviderBrand("__proto__")).not.toThrow();
    const brand = getProviderBrand("__proto__");
    expect(brand.label).toBe("__proto__");
    expect(typeof brand.Icon).toBe("function");
  });

  it("does not throw and does not return a prototype value for 'constructor'", () => {
    expect(() => getProviderBrand("constructor")).not.toThrow();
    const brand = getProviderBrand("constructor");
    expect(brand.label).toBe("constructor");
    expect(typeof brand.Icon).toBe("function");
  });
});

describe("NVIDIA_BRAND", () => {
  it("is the NVIDIA local-inference brand", () => {
    expect(NVIDIA_BRAND.label).toContain("NVIDIA");
    expect(NVIDIA_BRAND.isLocal).toBe(true);
    expect(NVIDIA_BRAND.accentColor).toBe("#76B900");
  });
});

describe("AMD_BRAND", () => {
  it("is the AMD local-inference brand", () => {
    expect(AMD_BRAND.label).toContain("AMD");
    expect(AMD_BRAND.isLocal).toBe(true);
    expect(AMD_BRAND.accentColor).toBe("#ED1C24");
  });
});

describe("getAcceleratorBadge", () => {
  it("returns null for non-ollama providers", () => {
    expect(getAcceleratorBadge("openai", "nvidia", "nvidia")).toBeNull();
    expect(getAcceleratorBadge("bedrock", "amd", null)).toBeNull();
  });

  it("returns null when providerType is null", () => {
    expect(getAcceleratorBadge(null, "nvidia", null)).toBeNull();
  });

  it("prefers explicit accelerator vendor over host GPU vendor", () => {
    const badge = getAcceleratorBadge("ollama", "amd", "nvidia");
    expect(badge?.label).toBe("AMD");
    expect(badge?.color).toBe(AMD_BRAND.accentColor);
  });

  it("falls back to host GPU vendor when accelerator is null (NVIDIA)", () => {
    const badge = getAcceleratorBadge("ollama", null, "nvidia");
    expect(badge?.label).toBe("NVIDIA");
    expect(badge?.color).toBe(NVIDIA_BRAND.accentColor);
  });

  it("falls back to host GPU vendor when accelerator is null (AMD)", () => {
    const badge = getAcceleratorBadge("ollama", null, "amd");
    expect(badge?.label).toBe("AMD");
  });

  it("returns null for ollama when neither explicit nor host vendor available", () => {
    expect(getAcceleratorBadge("ollama", null, null)).toBeNull();
    expect(getAcceleratorBadge("ollama", undefined, undefined)).toBeNull();
  });

  it("ignores unknown host GPU vendors", () => {
    expect(getAcceleratorBadge("ollama", null, "intel")).toBeNull();
  });
});

describe("isNvidiaLocalInference", () => {
  it("is true for ollama + nvidia", () => {
    expect(isNvidiaLocalInference("ollama", "nvidia")).toBe(true);
  });

  it("is true for ollama + NVIDIA (case-insensitive)", () => {
    expect(isNvidiaLocalInference("ollama", "NVIDIA")).toBe(true);
  });

  it("is false for non-ollama providers even with NVIDIA GPU", () => {
    expect(isNvidiaLocalInference("bedrock", "nvidia")).toBe(false);
    expect(isNvidiaLocalInference("openai", "nvidia")).toBe(false);
  });

  it("is false for ollama with non-nvidia GPU", () => {
    expect(isNvidiaLocalInference("ollama", "amd")).toBe(false);
    expect(isNvidiaLocalInference("ollama", "intel")).toBe(false);
  });

  it("is false for ollama with null/undefined GPU vendor", () => {
    expect(isNvidiaLocalInference("ollama", null)).toBe(false);
    expect(isNvidiaLocalInference("ollama", undefined)).toBe(false);
  });

  it("is false for null providerType", () => {
    expect(isNvidiaLocalInference(null, "nvidia")).toBe(false);
  });
});
