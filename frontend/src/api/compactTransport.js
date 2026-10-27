// Versioned, lossless transport. Expand fresh containers, not aliased objects:
// consumers keep the same mutation semantics as the original JSON.parse result.
export const COMPACT_TRANSPORT = "sigra-json-dictionary-v1";

export function expandTransport(value) {
  if (!value || typeof value !== "object" || value.transport !== COMPACT_TRANSPORT) return value;
  const fail = () => { throw new Error("Resposta compacta da API inválida."); };
  if (Object.keys(value).sort().join() !== "nodes,root,transport" || !Array.isArray(value.nodes)) fail();
  let visits = 0;
  function decode(item, depth = 0) {
    if (++visits > 5000000 || depth > 100) fail();
    if (item === null || typeof item !== "object") return item;
    if (Array.isArray(item) || Object.keys(item).join() !== "r" || !Number.isSafeInteger(item.r) || item.r < 0 || item.r >= value.nodes.length) fail();
    const node = value.nodes[item.r];
    if (!Array.isArray(node) || node.length !== 2 || !Array.isArray(node[1])) fail();
    if (node[0] === "a") return node[1].map((child) => decode(child, depth + 1));
    if (node[0] !== "o") fail();
    const result = {};
    for (const pair of node[1]) {
      if (!Array.isArray(pair) || pair.length !== 2 || typeof pair[0] !== "string" || Object.hasOwn(result, pair[0])) fail();
      // __proto__ is data, never a prototype assignment from a response.
      Object.defineProperty(result, pair[0], { value: decode(pair[1], depth + 1), enumerable: true, writable: true, configurable: true });
    }
    return result;
  }
  return decode(value.root);
}

export function csvRowText(value) {
  const fail = () => { throw new Error("Linha da exportação inválida."); };
  if (value?.schema !== "sigra-csv-dictionary-v1" || !Array.isArray(value.cells) || value.cells.length !== 36) fail();
  function tree(node, depth = 0) {
    if (depth > 100 || !Array.isArray(node) || node.length !== 2) fail();
    const [kind, content] = node;
    if (kind === "s" && typeof content === "string") return content;
    if (!Array.isArray(content)) fail();
    if (kind === "a") return `[${content.map((child) => tree(child, depth + 1)).join(",")}]`;
    if (kind === "o") return `{${content.map((pair) => {
      if (!Array.isArray(pair) || pair.length !== 2 || typeof pair[0] !== "string") fail();
      return `${JSON.stringify(pair[0])}:${tree(pair[1], depth + 1)}`;
    }).join(",")}}`;
    fail();
  }
  const cells = value.cells.map((cell) => {
    if (!Array.isArray(cell) || cell.length !== 2) fail();
    const text = cell[0] === "j" ? tree(cell[1]) : cell[0] === "t" && typeof cell[1] === "string" ? cell[1] : fail();
    return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
  });
  return `${cells.join(",")}\r\n`;
}

export async function sha256Hex(bytes) {
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, "0")).join("");
}
