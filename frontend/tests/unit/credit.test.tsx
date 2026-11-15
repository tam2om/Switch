import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AuthCard } from "@/components/AuthCard";
import { Credit } from "@/components/Credit";
import { buildCsp } from "@/middleware";

const TEXT = "Developed in-house by the AMCO Information Technology Department, 2026.";

describe("in-house credit and icon", () => {
  it("shows the credit text exactly", () => {
    render(<Credit />);
    expect(screen.getByText(TEXT)).toBeInTheDocument();
  });

  it("is shown on the sign-in card with the AMCO icon", () => {
    const { container } = render(<AuthCard title="Sign in"><span>form</span></AuthCard>);
    expect(screen.getByText(TEXT)).toBeInTheDocument();
    expect(container.querySelector('img[src="/icon-192.png"]')).not.toBeNull();
  });

  it("allows same-origin images for the icon", () => {
    expect(buildCsp("n", false)).toContain("img-src 'self'");
  });
});
