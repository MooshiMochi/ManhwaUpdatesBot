-- The V1 import preserved a literal 'All' folder from the old bot. The browser
-- already has an "All folders" filter that covers the same need, so the folder
-- is redundant — fold its bookmarks into Reading.
UPDATE bookmarks SET folder = 'Reading' WHERE folder = 'All';
