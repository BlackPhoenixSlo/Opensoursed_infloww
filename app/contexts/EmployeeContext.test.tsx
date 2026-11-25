import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup } from "@testing-library/react";

import { EmployeeProvider, useEmployee } from "@/contexts/EmployeeContext";
import type { Employee } from "@/lib/relay";
import { makeTestQueryClient, renderWithProviders } from "@/test-utils";

const USER = { user_id: "u1", username: "owner" };
vi.mock("@/contexts/UserContext", () => ({
  useUser: () => ({ user: USER, loading: false }),
  useOptionalUser: () => ({ user: USER, loading: false }),
}));

const relayGet = vi.fn(() => new Promise(() => {}));
vi.mock("@/lib/relay", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/relay")>();
  return { ...actual, relay: { ...actual.relay, get: () => relayGet() } };
});

const OWNER: Employee = { id: 3, display_name: "owner", color: "#888888", is_active: true, kind: "owner", user_id: "u1" };
const LOGIN: Employee = { id: 14, display_name: "Santan", color: "#8b5cf6", is_active: true, chatter_id: "c14",
  kind: "login", user_id: "u1" };
const RETIRED: Employee = { id: 27, display_name: "jackob", color: "#f59e0b", is_active: false, kind: "name",
  user_id: "u1" };

type Ctx = ReturnType<typeof useEmployee>;

function renderProvider(cached?: Employee[]) {
  const client = makeTestQueryClient();
  if (cached) client.setQueryData(["employees", "all"], { employees: cached });
  const renders: Ctx[] = [];
  function Probe() {
    renders.push(useEmployee());
    return null;
  }
  renderWithProviders(<EmployeeProvider><Probe /></EmployeeProvider>, client);
  return { first: renders[0], latest: () => renders[renders.length - 1] };
}

beforeEach(() => { window.localStorage.clear(); });
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("EmployeeContext", () => {
  it("acts as the owner's own row on the first render, with no pick", () => {
    const { first } = renderProvider([LOGIN, OWNER, RETIRED]);
    expect(first.current).toEqual(OWNER);
    expect(first.hydrated).toBe(true);
  });

  it("keeps every row in the roster, logins and retired names included", () => {
    const { first } = renderProvider([LOGIN, OWNER, RETIRED]);
    expect(first.roster).toEqual([LOGIN, OWNER, RETIRED]);
  });

  it("never acts as a login or a retired name, even with an old stored pick", () => {
    window.localStorage.setItem("chatterly:employee_id", "14");
    const { first } = renderProvider([LOGIN, RETIRED]);
    expect(first.current).toBeNull();
  });

  it("is not hydrated, and acts as no one, before the roster resolves", () => {
    const { first } = renderProvider();
    expect(first.roster).toEqual([]);
    expect(first.current).toBeNull();
    expect(first.hydrated).toBe(false);
  });
});
