import { describe, expect, it } from "vitest";
import { normalizeChannel, normalizeTag, orientationOf, resolutionLabelOf } from "../worker/lib/normalize";
import { parseRange } from "../worker/routes/media";
import { extractJson } from "../worker/routes/ai";

describe("normalizeTag", () => {
  it.each([
    ["#Закат", "закат"],
    ["##ночной_город", "ночной город"],
    ["  Много   пробелов ", "много пробелов"],
    ["#", null],
    ["", null],
  ])("%s → %s", (input, expected) => {
    expect(normalizeTag(input)).toBe(expected);
  });
});

describe("normalizeChannel", () => {
  it.each(["@My_Archive", "https://t.me/my_archive", "t.me/my_archive/15", "my_archive"])("%s", (input) => {
    expect(normalizeChannel(input)).toBe("my_archive");
  });
  it("отклоняет мусор", () => {
    expect(() => normalizeChannel("ab")).toThrow();
    expect(() => normalizeChannel("1channel")).toThrow();
  });
});

describe("ориентация и разрешение", () => {
  it.each([
    [640, 480, "horizontal", "SD"],
    [1280, 720, "horizontal", "HD"],
    [1920, 1080, "horizontal", "FullHD"],
    [1080, 1920, "vertical", "FullHD"],
    [1920, 800, "horizontal", "FullHD"],
    [1440, 1080, "horizontal", "FullHD"],
    [2560, 1440, "horizontal", "2K"],
    [3840, 2160, "horizontal", "4K"],
    [4096, 2160, "horizontal", "4K"],
    [7680, 4320, "horizontal", "8K"],
    [1080, 1080, "square", "FullHD"],
    [1000, 1040, "square", "HD"],
    [600, 600, "square", "SD"],
  ] as const)("%d×%d → %s %s", (w, h, orientation, label) => {
    expect(orientationOf(w, h)).toBe(orientation);
    expect(resolutionLabelOf(w, h)).toBe(label);
  });
});

describe("parseRange", () => {
  it("разбирает варианты", () => {
    expect(parseRange("bytes=0-9", 100)).toEqual({ start: 0, end: 9 });
    expect(parseRange("bytes=90-", 100)).toEqual({ start: 90, end: 99 });
    expect(parseRange("bytes=-10", 100)).toEqual({ start: 90, end: 99 });
    expect(parseRange("bytes=0-500", 100)).toEqual({ start: 0, end: 99 });
    expect(parseRange("bytes=100-", 100)).toBe("invalid");
    expect(parseRange("bytes=5-2", 100)).toBe("invalid");
    expect(parseRange("bytes=0-1,5-6", 100)).toBeNull();
    expect(parseRange("items=0-1", 100)).toBeNull();
  });
});

describe("extractJson", () => {
  it("достаёт JSON из ответа модели", () => {
    expect(extractJson('```json\n{"a":1}\n```')).toEqual({ a: 1 });
    expect(extractJson('Ответ: {"tags":["x"]} — готово')).toEqual({ tags: ["x"] });
    expect(extractJson("нет json")).toBeNull();
    expect(extractJson("[1,2]")).toBeNull();
  });
});
