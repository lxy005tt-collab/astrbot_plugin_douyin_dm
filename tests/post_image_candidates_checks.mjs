import assert from 'node:assert/strict';
import {postImageCandidates,postImages} from '../mimi_douyin/browser/post_media.mjs';

const detail={image_post_info:{images:[
  {display_image:{url_list:['https://display.invalid/1','https://display.invalid/1']},owner_watermark_image:{url_list:['https://owner.invalid/1']},url_list:['http://ignored.invalid/1']},
  {display_image:{url_list:[]},url_list:['https://original.invalid/2','https://original-backup.invalid/2']},
  {display_image:{url_list:[]},url_list:[]}
]}};
const candidates=postImageCandidates(detail);
assert.deepEqual(candidates,[
  ['https://display.invalid/1','https://owner.invalid/1'],
  ['https://original.invalid/2','https://original-backup.invalid/2'],
  []
]);
assert.deepEqual(postImages(detail),['https://display.invalid/1','https://original.invalid/2',undefined]);
console.log('post image candidate checks: 3 images, ordered unique HTTPS candidates, missing slot preserved');
