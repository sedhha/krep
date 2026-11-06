import { createProxy } from "@/lib/proxy";
import { getLoginToken } from "@/lib/session";

const proxy = createProxy({
  upstreamUrl: process.env.KREP_API_URL ?? "http://localhost:8000",
  getToken: getLoginToken,
});

export {
  proxy as DELETE,
  proxy as GET,
  proxy as HEAD,
  proxy as OPTIONS,
  proxy as PATCH,
  proxy as POST,
  proxy as PUT,
};
