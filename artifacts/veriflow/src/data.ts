export type Product = {
  id: string; name: string; vendor: string; website: string; description: string;
  categories: string[]; aliases: string[]; createdAt: string;
};
export type Review = {
  id: string; productId: string; productName: string; sourceName: string; sourceUrl: string;
  originalReviewId: string; reviewType: string; title: string; reviewText: string;
  authorAttribution: string; ratingValue: string; ratingScale: string; publishedAt: string;
  collectedAt: string; licenseName: string; licenseUrl: string; retentionAllowed: boolean;
  exportAllowed: boolean; attributionText: string; modificationMarker: string;
  duplicateOf: string; createdAt: string;
};
export type WorkbenchData = { products: Product[]; reviews: Review[] };

export const categories = [
  'Artificial Intelligence & AI Tools','Website Design & Development','Digital Marketing','Social Media Management',
  'Search Engine Optimization','Analytics & Business Intelligence','Email Marketing','Customer Relationship Management',
  'E-commerce','Website Hosting','Domains & DNS','Graphic Design','Video Editing','Audio Production','Productivity',
  'Project Management','Business Management','Accounting & Finance','Customer Support','Sales Automation','Cybersecurity',
  'VPN & Privacy','Cloud Computing','Developer Tools','No-Code & Low-Code','Mobile App Development','Education & Learning',
  'Course Creation','Human Resources','Scheduling & Booking','Automation & Integrations','Content Management',
  'Writing & Publishing','Data Management','Other Software'
];

const reviewNames = [
  'G2','Capterra','Trustpilot','TrustRadius','GetApp','Software Advice','Gartner Peer Insights','PeerSpot',
  'SourceForge','Slashdot Software','SoftwareReviews','SoftwareSuggest','SaaSworthy','Crozdesk','Serchen',
  'GoodFirms','CompareCamp','SaaSGenius','SoftwareWorld','Tekpon','Trustindex','lib.reviews'
];
const discoveryNames = [
  'AlternativeTo','SaaSHub','Product Hunt','AppSumo','StackShare','Toolify','Futurepedia','There’s An AI For That',
  'TopAI.tools','FutureTools','Toolradar','Uneed','BetaList','Indie Hackers'
];
const slugs: Record<string,string> = {
  G2:'g2.com', Capterra:'capterra.com', Trustpilot:'trustpilot.com', TrustRadius:'trustradius.com',
  GetApp:'getapp.com', 'Software Advice':'softwareadvice.com', 'Gartner Peer Insights':'gartner.com/reviews',
  PeerSpot:'peerspot.com', SourceForge:'sourceforge.net', 'Slashdot Software':'slashdot.org/software',
  SoftwareReviews:'softwarereviews.com', SoftwareSuggest:'softwaresuggest.com', SaaSworthy:'saasworthy.com',
  Crozdesk:'crozdesk.com', Serchen:'serchen.com', GoodFirms:'goodfirms.co', CompareCamp:'comparecamp.com',
  SaaSGenius:'saasgenius.com', SoftwareWorld:'softwareworld.co', Tekpon:'tekpon.com', Trustindex:'trustindex.io',
  'lib.reviews':'lib.reviews', AlternativeTo:'alternativeto.net', SaaSHub:'saashub.com',
  'Product Hunt':'producthunt.com', AppSumo:'appsumo.com', StackShare:'stackshare.io', Toolify:'toolify.ai',
  Futurepedia:'futurepedia.io', 'There’s An AI For That':'theresanaiforthat.com', 'TopAI.tools':'topai.tools',
  FutureTools:'futuretools.io', Toolradar:'toolradar.io', Uneed:'uneed.best', BetaList:'betalist.com',
  'Indie Hackers':'indiehackers.com'
};
export const sources = [
  ...reviewNames.map(name => ({ name, kind:'Review platform', reviewType:'Verified customer review / app rating', url:`https://${slugs[name]}` })),
  ...discoveryNames.map(name => ({ name, kind:'Discovery directory', reviewType:'Discovery listing', url:`https://${slugs[name]}` }))
];

const STORAGE_KEY = 'veriflow-workbench-v1';
export function readWorkbench(): WorkbenchData {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { products: [], reviews: [] };
    const value = JSON.parse(raw);
    if (Array.isArray(value.products) && Array.isArray(value.reviews)) return value;
  } catch { /* A damaged local record is not silently overwritten. */ }
  return { products: [], reviews: [] };
}
export function saveWorkbench(value: WorkbenchData) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
}
export function isWorkbenchShape(value: unknown): value is WorkbenchData {
  if (!value || typeof value !== 'object') return false;
  const v = value as WorkbenchData;
  if (!Array.isArray(v.products) || !Array.isArray(v.reviews)) return false;
  const productKeys = ['id','name','vendor','website','description','categories','aliases','createdAt'];
  const reviewKeys = ['id','productId','productName','sourceName','sourceUrl','originalReviewId','reviewType','title','reviewText','authorAttribution','ratingValue','ratingScale','publishedAt','collectedAt','licenseName','licenseUrl','retentionAllowed','exportAllowed','attributionText','modificationMarker','duplicateOf','createdAt'];
  return v.products.every(p => p && productKeys.every(k => k in p) && Array.isArray(p.categories) && Array.isArray(p.aliases))
    && v.reviews.every(r => r && reviewKeys.every(k => k in r) && typeof r.retentionAllowed === 'boolean' && typeof r.exportAllowed === 'boolean');
}
export { STORAGE_KEY };
